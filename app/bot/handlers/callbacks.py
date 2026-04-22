"""
handlers/callbacks.py
─────────────────────
Handles all Telegram inline keyboard button presses (CallbackQueryHandler).

Callback data values and their meaning:
┌────────────────────┬────────────────────────────────────────────────────────┐
│ callback_data      │ Action                                                 │
├────────────────────┼────────────────────────────────────────────────────────┤
│ approve            │ Resume agent with "approve" — executes add             │
│ reject_and_retry   │ Resume agent with "reject_and_retry"                   │
│ edit               │ Resume agent with "edit"                               │
│ abort              │ Resume agent with "reject" silently; tell user aborted │
│ del_toggle_<idx>   │ Toggle document at absolute index in delete selection  │
│ del_page_<n>       │ Navigate to page n in multi-delete list                │
│ del_confirm        │ Execute deletion of all selected documents             │
│ del_abort          │ Cancel the pending delete; close the agent thread      │
│ confirm_update     │ Apply the pending update (agent already proposed)      │
│ abort_update       │ Cancel the pending update; close the agent thread      │
│ refine_update      │ Ask user to clarify which document they meant          │
└────────────────────┴────────────────────────────────────────────────────────┘
"""

import logging
from langgraph.types import Command
from telegram import InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.bot.formatting import format_agent_response
from app.bot.hitl import build_multi_delete_text, build_multi_delete_keyboard
from app.bot.update_flow import apply_direct_update, build_update_summary

logger = logging.getLogger("bot")


def _agent_config(chat_id: int, vs) -> dict:
    return {"configurable": {"thread_id": str(chat_id), "vs": vs}}


def _reject_command(message: str = "User aborted.") -> Command:
    return Command(resume={"decisions": [{"type": "reject", "message": message}]})


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat.id
    data = query.data
    logger.info(f"[callback] user_id={user_id}, chat_id={chat_id}: {data!r}")

    try:
        await query.answer()
    except Exception as e:
        logger.warning(f"[callback] query.answer() failed — stale/duplicate callback, ignoring: {e}")
        return

    try:
        vs    = context.bot_data["vs"]
        agent = context.bot_data["agent"]
        config = _agent_config(chat_id, vs)

        # ── Abort (add flow) ──────────────────────────────────────────────────
        if data == "abort":
            try:
                agent.invoke(_reject_command("User aborted."), config=config)
            except Exception as e:
                logger.warning(f"[callback] abort: agent resume failed (non-fatal): {e}")
            await query.edit_message_text("❌ Action aborted. No changes were made.")
            return

        # ── Multi-delete: refine search ───────────────────────────────────────
        if data == "del_refine":
            await query.edit_message_text(
                "🔍 Describe what you'd like to delete:\n"
                '  - e.g. "all books with status=to_read"\n'
                "  - or a specific title"
            )
            context.user_data["refining_delete_search"] = True
            return

        # ── Multi-delete: abort ───────────────────────────────────────────────
        if data == "del_abort":
            try:
                agent.invoke(_reject_command("User aborted the delete."), config=config)
            except Exception as e:
                logger.warning(f"[callback] del_abort: agent resume failed (non-fatal): {e}")
            context.user_data.pop("pending_delete_docs",     None)
            context.user_data.pop("pending_delete_filters",  None)
            context.user_data.pop("pending_delete_selected", None)
            context.user_data.pop("pending_delete_page",     None)
            await query.edit_message_text("❌ Delete cancelled. No changes were made.")
            return

        # ── Multi-delete: toggle selection ────────────────────────────────────
        if data.startswith("del_toggle_"):
            idx = int(data.split("_")[-1])
            selected: set = context.user_data.get("pending_delete_selected", set())
            if idx in selected:
                selected.discard(idx)
            else:
                selected.add(idx)
            context.user_data["pending_delete_selected"] = selected
            docs = context.user_data.get("pending_delete_docs", [])
            page = context.user_data.get("pending_delete_page", 0)
            text = build_multi_delete_text(docs, selected, page)
            keyboard = build_multi_delete_keyboard(docs, selected, page)
            await query.edit_message_text(
                text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return

        # ── Multi-delete: change page ─────────────────────────────────────────
        if data.startswith("del_page_"):
            page = int(data.split("_")[-1])
            context.user_data["pending_delete_page"] = page
            docs     = context.user_data.get("pending_delete_docs", [])
            selected = context.user_data.get("pending_delete_selected", set())
            text = build_multi_delete_text(docs, selected, page)
            keyboard = build_multi_delete_keyboard(docs, selected, page)
            await query.edit_message_text(
                text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return

        # ── Multi-delete: confirm ─────────────────────────────────────────────
        if data == "del_confirm":
            selected: set = context.user_data.get("pending_delete_selected", set())
            docs: list    = context.user_data.get("pending_delete_docs", [])

            if not selected:
                await query.answer("⚠️ Select at least one item first.", show_alert=True)
                return

            # Close the interrupted agent thread cleanly
            try:
                agent.invoke(_reject_command("Applying delete directly."), config=config)
            except Exception as e:
                logger.warning(f"[callback] del_confirm: agent resume failed (non-fatal): {e}")

            deleted_titles = []
            errors = []
            for idx in sorted(selected):
                doc = docs[idx]
                doc_meta = doc.get("metadata", {})
                doc_id   = doc_meta.get("id")
                doc_text = doc.get("text", f"Item {idx + 1}")
                try:
                    if doc_id:
                        await vs.delete({"id": doc_id})
                    else:
                        # Fall back to filters stored during interrupt
                        filters = context.user_data.get("pending_delete_filters", {})
                        await vs.delete(filters)
                    deleted_titles.append(doc_text)
                    logger.info(f"[callback] del_confirm: deleted doc_id={doc_id!r}, text={doc_text!r}")
                except Exception as e:
                    logger.error(f"[callback] del_confirm: failed to delete idx={idx}: {e}", exc_info=True)
                    errors.append(doc_text)

            # Clear pending state
            context.user_data.pop("pending_delete_docs",     None)
            context.user_data.pop("pending_delete_filters",  None)
            context.user_data.pop("pending_delete_selected", None)
            context.user_data.pop("pending_delete_page",     None)

            if deleted_titles:
                titles_str = "\n".join(f"  • {t}" for t in deleted_titles)
                msg = f"🗑️ Deleted {len(deleted_titles)} item(s):\n{titles_str}"
            else:
                msg = "⚠️ No items were deleted."
            if errors:
                err_str = "\n".join(f"  • {t}" for t in errors)
                msg += f"\n\n❌ Failed to delete:\n{err_str}"

            await query.edit_message_text(msg)
            return

        # ── Abort update flow ─────────────────────────────────────────────────
        if data == "abort_update":
            try:
                agent.invoke(_reject_command("User aborted the update."), config=config)
            except Exception as e:
                logger.warning(f"[callback] abort_update: agent resume failed (non-fatal): {e}")
            context.user_data.pop("pending_update_doc",          None)
            context.user_data.pop("pending_update_filters",      None)
            context.user_data.pop("pending_update_new_metadata", None)
            await query.edit_message_text("❌ Update cancelled. No changes were made.")
            return

        # ── Confirm update ────────────────────────────────────────────────────
        if data == "confirm_update":
            try:
                agent.invoke(
                    Command(resume={"decisions": [{"type": "reject", "message": "Applying update directly."}]}),
                    config=config,
                )
            except Exception as e:
                logger.warning(f"[callback] confirm_update: agent resume failed (non-fatal): {e}")

            pending_filters      = context.user_data.pop("pending_update_filters",      None)
            pending_new_metadata = context.user_data.pop("pending_update_new_metadata", {})
            pending_doc          = context.user_data.pop("pending_update_doc",          None)

            if pending_new_metadata and pending_filters:
                try:
                    new_text, new_metadata = await apply_direct_update(vs, pending_filters, pending_new_metadata)
                    summary = build_update_summary(new_text, new_metadata)
                    await query.edit_message_text(
                        f"✅ Document updated!\n\n<b>Changes applied:</b>\n{summary}",
                        parse_mode="HTML",
                    )
                    logger.info(f"[callback] confirm_update: done. filters={pending_filters}")
                except Exception as e:
                    logger.error(f"[callback] confirm_update: update failed: {e}", exc_info=True)
                    await query.edit_message_text(f"❌ Update failed: {e}")
            else:
                # Agent didn't propose specific changes — ask the user.
                # Put state back so chat.py can use it when the user replies.
                context.user_data["pending_update_filters"] = pending_filters
                context.user_data["pending_update_doc"]     = pending_doc
                await query.edit_message_text("✏️ Please describe what changes you'd like to make.")
                context.user_data["awaiting_update_changes"] = True
            return

        # ── Refine: user wants a different document ───────────────────────────
        if data == "refine_update":
            await query.edit_message_text(
                "🔍 Please describe the document you're looking for:\n"
                "  - Use natural language, or\n"
                "  - Specify metadata (e.g. 'task with status=done')"
            )
            context.user_data["refining_update_search"] = True
            return

        # ── Standard HITL decisions (approve / reject_and_retry / edit) ──────
        decision = [{"type": data}]
        logger.debug(f"[callback] Resuming agent with decision: {decision}")
        final_result = agent.invoke(
            Command(resume={"decisions": decision}),
            config=config,
        )

        if data == "approve":
            last_tool_call = None
            for msg in final_result.get("messages", []):
                if getattr(msg, "tool_calls", None):
                    last_tool_call = msg.tool_calls[-1]

            if last_tool_call:
                action = last_tool_call.get("name", "")
                if action == "add_to_vault":
                    confirmation = "✅ Item successfully added to your vault."
                elif action == "delete_from_vault":
                    confirmation = "🗑️ Item(s) successfully deleted from your vault."
                else:
                    confirmation = format_agent_response(final_result["messages"][-1].content)
            else:
                confirmation = format_agent_response(final_result["messages"][-1].content)
        else:
            confirmation = format_agent_response(final_result["messages"][-1].content)

        if query.message.text != confirmation:
            await query.edit_message_text(confirmation)
        logger.info(f"[callback] Final message sent: {confirmation!r}")

    except Exception as e:
        logger.error(f"[callback] Exception: {e}", exc_info=True)
