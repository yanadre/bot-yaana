"""
handlers/callbacks.py
─────────────────────
Handles all Telegram inline keyboard button presses (CallbackQueryHandler).

Callback data values and their meaning:
┌──────────────────────────────┬──────────────────────────────────────────────────────────────┐
│ callback_data                │ Action                                                       │
├──────────────────────────────┼──────────────────────────────────────────────────────────────┤
│ approve                      │ Resume agent with "approve" — executes add                   │
│ reject_and_retry             │ Resume agent with "reject_and_retry"                         │
│ edit                         │ Resume agent with "edit"                                     │
│ abort                        │ Resume agent with "reject" silently; tell user aborted       │
│ del_toggle_<idx>             │ Toggle document at absolute index in delete selection        │
│ del_page_<n>                 │ Navigate to page n in multi-delete list                      │
│ del_confirm                  │ Execute deletion of all selected documents                   │
│ del_abort                    │ Cancel the pending delete; close the agent thread            │
│ confirm_update               │ Apply the pending update (agent already proposed)            │
│ abort_update                 │ Cancel the pending update; close the agent thread            │
│ refine_update                │ Ask user to clarify which document they meant                │
│ list_open_<doc_id>           │ Open a list document by id (from the picker)                 │
│ list_toggle_<doc_id>_<idx>   │ Toggle checked state of item at index in a list doc          │
│ list_page_<doc_id>_<page>    │ Navigate to page in a list doc                               │
│ list_add_<doc_id>            │ Prompt user to type a new item (or show task form)           │
│ list_clear_<doc_id>          │ Ask confirmation before removing done items                  │
│ list_clear_confirm_<doc_id>  │ Execute removal of done items (after confirmation)           │
│ list_catfilter_<doc_id>|<c>  │ Set category filter to <c>; empty string clears it           │
│ task_form_p_<doc_id>|…       │ Set priority in new-task form                                │
│ task_form_e_<doc_id>|…       │ Set effort in new-task form                                  │
│ task_form_c_<doc_id>|…       │ Set category in new-task form (from existing list)           │
│ task_form_newcat_<doc_id>    │ Prompt user to type a custom category name                   │
│ task_form_add_<doc_id>|…     │ Commit new task from form                                    │
│ task_form_cancel_<doc_id>    │ Cancel new-task form                                         │
└──────────────────────────────┴──────────────────────────────────────────────────────────────┘
"""

import logging
from datetime import datetime, timezone

from langgraph.types import Command
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.bot.formatting import format_agent_response
from app.bot.hitl import build_multi_delete_text, build_multi_delete_keyboard
from app.bot.list_service import fetch_doc, save_items, render_list, edit_list_message
from app.bot.lists import render_task_form_text, render_task_form_keyboard
from app.bot.structure_types import make_item
from app.bot.update_flow import apply_direct_update, build_update_summary
from app.bot.session import get_thread_id, touch_session

logger = logging.getLogger("bot")


def _agent_config(chat_id: int, user_data: dict, vs) -> dict:
    return {"configurable": {"thread_id": get_thread_id(chat_id, user_data), "vs": vs}}


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
        config = _agent_config(chat_id, context.user_data, vs)

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

        # ── List: toggle show/hide done items ────────────────────────────────
        if data.startswith("list_showdone_"):
            parts     = data.split("_")
            doc_id    = "_".join(parts[2:-1])
            show_done = parts[-1] == "1"
            context.user_data[f"list_showdone_{doc_id}"] = show_done
            doc = await fetch_doc(vs, doc_id)
            if not doc:
                await query.edit_message_text("❌ List not found.")
                return
            await edit_list_message(context.bot, query.message.chat_id, query.message.message_id, doc, context, doc_id)
            return

        # ── List: set category filter ─────────────────────────────────────────
        if data.startswith("list_catfilter_"):
            # format: list_catfilter_<doc_id>|<idx>  (empty = clear filter, digit = category index)
            rest     = data[len("list_catfilter_"):]
            doc_id, _, raw = rest.partition("|")
            doc = await fetch_doc(vs, doc_id)
            if not doc:
                await query.edit_message_text("❌ List not found.")
                return
            if raw == "" or not raw.isdigit():
                # Clear filter
                category = None
            else:
                # Resolve index to category name using the same sorted list as the keyboard
                all_items  = doc.get("metadata", {}).get("items", [])
                categories = sorted({i.get("category", "") for i in all_items if i.get("category")})
                idx = int(raw)
                category = categories[idx] if idx < len(categories) else None
            context.user_data[f"list_category_{doc_id}"] = category
            context.user_data[f"list_page_{doc_id}"]     = 0       # reset page on filter change
            await edit_list_message(context.bot, query.message.chat_id, query.message.message_id, doc, context, doc_id)
            return

        # ── List: open from picker ────────────────────────────────────────────
        if data.startswith("list_open_"):
            doc_id = data[len("list_open_"):]
            context.user_data[f"list_page_{doc_id}"] = 0   # reset to page 0
            doc = await fetch_doc(vs, doc_id)
            if not doc:
                await query.edit_message_text("❌ List not found.")
                return
            await edit_list_message(context.bot, query.message.chat_id, query.message.message_id, doc, context, doc_id)
            return

        # ── List: toggle item checked state ───────────────────────────────────
        if data.startswith("list_toggle_"):
            parts  = data.split("_")
            idx    = int(parts[-1])
            doc_id = "_".join(parts[2:-1])

            doc = await fetch_doc(vs, doc_id)
            if not doc:
                await query.edit_message_text("❌ List not found.")
                return

            meta  = doc.get("metadata", {})
            items = list(meta.get("items", []))
            if idx >= len(items):
                await query.answer("⚠️ Item not found.", show_alert=True)
                return

            now = datetime.now(timezone.utc).isoformat()
            items[idx]["checked"]    = not items[idx].get("checked", False)
            items[idx]["checked_at"] = now if items[idx]["checked"] else None
            await save_items(vs, doc_id, meta, items)

            doc = await fetch_doc(vs, doc_id) or doc
            await edit_list_message(context.bot, query.message.chat_id, query.message.message_id, doc, context, doc_id)
            return

        # ── List: change page ─────────────────────────────────────────────────
        if data.startswith("list_page_"):
            parts  = data.split("_")
            page   = int(parts[-1])
            doc_id = "_".join(parts[2:-1])
            context.user_data[f"list_page_{doc_id}"] = page
            doc = await fetch_doc(vs, doc_id)
            if not doc:
                await query.edit_message_text("❌ List not found.")
                return
            await edit_list_message(context.bot, query.message.chat_id, query.message.message_id, doc, context, doc_id)
            return

        # ── List: toggle edit mode ────────────────────────────────────────────
        if data.startswith("list_editmode_"):
            parts   = data.split("_")
            active  = parts[-1] == "1"
            doc_id  = "_".join(parts[2:-1])
            context.user_data[f"list_editmode_{doc_id}"] = active
            doc = await fetch_doc(vs, doc_id)
            if not doc:
                await query.edit_message_text("❌ List not found.")
                return
            await edit_list_message(context.bot, query.message.chat_id, query.message.message_id, doc, context, doc_id)
            return

        # ── List: delete a single item ────────────────────────────────────────
        if data.startswith("list_item_del_"):
            parts  = data.split("_")
            idx    = int(parts[-1])
            doc_id = "_".join(parts[3:-1])
            doc = await fetch_doc(vs, doc_id)
            if not doc:
                await query.edit_message_text("❌ List not found.")
                return
            meta  = doc.get("metadata", {})
            items = list(meta.get("items", []))
            if idx >= len(items):
                await query.answer("⚠️ Item not found.", show_alert=True)
                return
            items.pop(idx)
            await save_items(vs, doc_id, meta, items)
            doc = await fetch_doc(vs, doc_id) or doc
            await edit_list_message(context.bot, query.message.chat_id, query.message.message_id, doc, context, doc_id)
            return

        # ── List: prompt to edit a single item's text ─────────────────────────
        if data.startswith("list_item_edit_"):
            parts  = data.split("_")
            idx    = int(parts[-1])
            doc_id = "_".join(parts[3:-1])
            context.user_data["pending_list_item_edit_doc_id"]     = doc_id
            context.user_data["pending_list_item_edit_idx"]        = idx
            context.user_data["pending_list_item_edit_message_id"] = query.message.message_id
            doc = await fetch_doc(vs, doc_id)
            old_text = ""
            if doc:
                items    = doc.get("metadata", {}).get("items", [])
                old_text = items[idx].get("text", "") if idx < len(items) else ""
            prompt = await query.message.reply_text(
                f"✏️ Send the new text for this item:\n<i>Current: {old_text}</i>",
                parse_mode="HTML",
            )
            context.user_data["pending_list_item_edit_prompt_id"] = prompt.message_id
            return

        # ── List: prompt to rename ────────────────────────────────────────────
        if data.startswith("list_rename_"):
            doc_id = data[len("list_rename_"):]
            context.user_data["pending_list_rename_doc_id"]     = doc_id
            context.user_data["pending_list_rename_message_id"] = query.message.message_id
            prompt = await query.message.reply_text("✏️ Send me the new name for this list:")
            context.user_data["pending_list_rename_prompt_id"]  = prompt.message_id
            return

        # ── List: prompt to add a new item (or show task form) ───────────────
        if data.startswith("list_add_"):
            doc_id = data[len("list_add_"):]
            doc    = await fetch_doc(vs, doc_id)
            item_type = doc.get("metadata", {}).get("item_type", "") if doc else ""

            if item_type == "task_list":
                # Task list → prompt for name first, then show the form
                context.user_data["pending_list_add_doc_id"]     = doc_id
                context.user_data["pending_list_add_message_id"] = query.message.message_id
                context.user_data["pending_task_form_mode"]      = True
                prompt = await query.message.reply_text("✏️ Send me the task name:")
                context.user_data["pending_list_add_prompt_id"]  = prompt.message_id
            else:
                # Other list types → simple text prompt
                context.user_data["pending_list_add_doc_id"]     = doc_id
                context.user_data["pending_list_add_message_id"] = query.message.message_id
                prompt = await query.message.reply_text(
                    "✏️ Send me the item you'd like to add:",
                    parse_mode="HTML",
                )
                context.user_data["pending_list_add_prompt_id"] = prompt.message_id
            return

        # ── Task form: field toggle (priority / effort / category) ────────────
        if (data.startswith("task_form_p_") or
                data.startswith("task_form_e_") or
                data.startswith("task_form_c_")):
            # format: task_form_<field>_<doc_id>|<new_value>
            field    = data[10]          # 'p', 'e', or 'c'
            rest     = data[12:]         # after "task_form_X_"
            doc_id, _, new_val = rest.partition("|")

            # Read current form state from user_data
            form = context.user_data.get(f"task_form_{doc_id}", {})
            if field == "p": form["priority"] = new_val or None
            if field == "e": form["effort"]   = new_val or None
            if field == "c":
                if new_val in ("", "x"):
                    # deselect
                    form["category"] = None
                elif new_val.isdigit():
                    # resolve index to category name
                    cats = form.get("existing_cats", [])
                    idx  = int(new_val)
                    form["category"] = cats[idx] if idx < len(cats) else None
                else:
                    form["category"] = new_val or None
            context.user_data[f"task_form_{doc_id}"] = form

            task_name = form.get("task_name", "")
            priority  = form.get("priority")
            effort    = form.get("effort")
            category  = form.get("category")
            existing_cats = form.get("existing_cats", [])

            # If for some reason it's missing, fall back to fetching from the doc
            if not existing_cats:
                doc = await fetch_doc(vs, doc_id)
                existing_cats = sorted({i.get("category", "") for i in doc.get("metadata", {}).get("items", []) if i.get("category")}) if doc else []
                form["existing_cats"] = existing_cats
                context.user_data[f"task_form_{doc_id}"] = form

            text     = render_task_form_text(task_name, priority, effort, category)
            keyboard = render_task_form_keyboard(doc_id, task_name, priority, effort, category, existing_cats)
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
            return

        # ── Task form: commit ─────────────────────────────────────────────────
        if data.startswith("task_form_add_"):
            doc_id = data[len("task_form_add_"):]
            form   = context.user_data.pop(f"task_form_{doc_id}", {})

            task_name = form.get("task_name", "")
            priority  = form.get("priority")
            effort    = form.get("effort")
            category  = form.get("category")

            doc = await fetch_doc(vs, doc_id)
            if not doc:
                await query.edit_message_text("❌ List not found.")
                return

            meta  = doc.get("metadata", {})
            items = list(meta.get("items", []))
            new_item = make_item(task_name, item_type="task_list",
                                 priority=priority, effort=effort, category=category)
            items.append(new_item)
            await save_items(vs, doc_id, meta, items)

            doc = await fetch_doc(vs, doc_id) or doc

            # Delete the task-form message, then send the list UI as a fresh message
            try:
                await query.message.delete()
            except Exception as e:
                logger.warning(f"[callback] could not delete task form message: {e}")

            text, keyboard = render_list(doc, context, doc_id)
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return

        # ── Task form: cancel ─────────────────────────────────────────────────
        if data.startswith("task_form_cancel_"):
            doc_id = data[len("task_form_cancel_"):]
            context.user_data.pop(f"task_form_{doc_id}", None)
            doc = await fetch_doc(vs, doc_id)
            if doc:
                await edit_list_message(context.bot, query.message.chat_id, query.message.message_id, doc, context, doc_id)
            else:
                await query.edit_message_text("❌ Cancelled.")
            return

        # ── Task form: prompt for custom category ─────────────────────────────
        if data.startswith("task_form_newcat_"):
            doc_id = data[len("task_form_newcat_"):]
            context.user_data["pending_task_form_newcat_doc_id"]     = doc_id
            context.user_data["pending_task_form_newcat_message_id"] = query.message.message_id
            prompt = await query.message.reply_text("🏷 Send me the category name:")
            context.user_data["pending_task_form_newcat_prompt_id"]  = prompt.message_id
            return

        # ── List: change type — show type picker ──────────────────────────────
        if data.startswith("list_settype_confirm_"):
            # format: list_settype_confirm_<doc_id>|<new_type>
            rest   = data[len("list_settype_confirm_"):]
            doc_id, _, new_type = rest.partition("|")
            doc = await fetch_doc(vs, doc_id)
            if not doc:
                await query.edit_message_text("❌ List not found.")
                return
            meta = doc.get("metadata", {})
            await vs.update_document(
                filter_dict={"id": doc_id},
                new_metadata={"item_type": new_type},
            )
            doc = await fetch_doc(vs, doc_id) or doc
            await edit_list_message(context.bot, query.message.chat_id, query.message.message_id, doc, context, doc_id)
            return

        if data.startswith("list_settype_"):
            doc_id      = data[len("list_settype_"):]
            current_doc = await fetch_doc(vs, doc_id)
            current_type = (current_doc or {}).get("metadata", {}).get("item_type", "")
            buttons = []
            for type_key, info in STRUCTURED_TYPES.items():
                mark  = "✦ " if type_key == current_type else ""
                label = f"{mark}{info['emoji']} {info['label']}"
                buttons.append([InlineKeyboardButton(
                    label,
                    callback_data=f"list_settype_confirm_{doc_id}|{type_key}",
                )])
            buttons.append([InlineKeyboardButton("❌ Cancel", callback_data=f"list_open_{doc_id}")])
            await query.edit_message_text(
                "🔄 Choose a new type for this list:",
                reply_markup=InlineKeyboardMarkup(buttons),
            )
            return

        # ── List: remove done items ───────────────────────────────────────────
        if data.startswith("list_clear_confirm_"):
            doc_id = data[len("list_clear_confirm_"):]
            doc    = await fetch_doc(vs, doc_id)
            if not doc:
                await query.edit_message_text("❌ List not found.")
                return
            meta  = doc.get("metadata", {})
            items = [i for i in meta.get("items", []) if not i.get("checked")]
            await save_items(vs, doc_id, meta, items)
            doc = await fetch_doc(vs, doc_id) or doc
            await edit_list_message(context.bot, query.message.chat_id, query.message.message_id, doc, context, doc_id)
            return

        if data.startswith("list_clear_"):
            doc_id     = data[len("list_clear_"):]
            doc        = await fetch_doc(vs, doc_id)
            if not doc:
                await query.edit_message_text("❌ List not found.")
                return
            done_count = sum(1 for i in doc.get("metadata", {}).get("items", []) if i.get("checked"))
            await query.edit_message_text(
                f"🗑️ Remove <b>{done_count} done item{'s' if done_count != 1 else ''}</b> permanently?\n"
                "<i>This cannot be undone.</i>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ Yes, remove", callback_data=f"list_clear_confirm_{doc_id}"),
                    InlineKeyboardButton("❌ Cancel",      callback_data=f"list_open_{doc_id}"),
                ]]),
            )
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

        try:
            if query.message.text != confirmation:
                await query.edit_message_text(confirmation)
        except Exception as e:
            if "Message is not modified" in str(e):
                pass   # user tapped the button twice — safe to ignore
            else:
                raise
        logger.info(f"[callback] Final message sent: {confirmation!r}")

    except Exception as e:
        logger.error(f"[callback] Exception: {e}", exc_info=True)
