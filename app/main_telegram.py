import logging
import sys
import os
from logging.handlers import WatchedFileHandler
from langchain.agents import create_agent
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, Application, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters


from app.models.embedding_model import StubEmbeddingModel, GeminiEmbeddingModel
from app.database.vector_store import QdrantStore
from app.agent.tools import tools

from app.config import settings


# Set up logging to both file and console
log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler = WatchedFileHandler('/app/logs/bot.log')  # [LOGGING] Use WatchedFileHandler for Docker volume
file_handler.setFormatter(log_formatter)
stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(log_formatter)

logger = logging.getLogger("bot")  # [LOG] Use named logger for all modules
logger.setLevel(logging.INFO)
logger.addHandler(file_handler)
logger.addHandler(stream_handler)
# Do NOT set propagate to False, allow propagation for submodules
# logger.propagate = False  # REMOVE THIS LINE

print("Logging to:", os.path.abspath('/app/logs/bot.log'))  # [LOG PATH INFO]

async def on_startup(app: Application):
    logger.info("\n\n==== BOT SESSION START ====")  # [SESSION MARKER]
    logger.info("Starting up application and initializing vector store and agent.")  # [LOG]
    # embedding =  StubEmbeddingModel(vector_size=VECTOR_SIZE)
    embedding =  GeminiEmbeddingModel(api_key=settings.GOOGLE_API_KEY, 
                                      embedding_model=settings.EMBEDDING_MODEL_NAME,
                                      vector_size=settings.EMBEDDING_VECTOR_SIZE)

    app.bot_data["vs"] = QdrantStore(
        host=settings.QDRANT_HOST,
        port=settings.QDRANT_PORT,
        collection_name=settings.QDRANT_COLLECTION_NAME,
        embedding_model=embedding
    )
    await app.bot_data["vs"].initialize()
    logger.info("[on_startup] Calling print_all_documents to list Qdrant collection contents...")
    try:
        app.bot_data["vs"].print_all_documents(limit=100)  # DEBUG: Print all docs in Qdrant
        logger.info("[on_startup] print_all_documents completed.")
    except Exception as e:
        logger.error(f"[on_startup] Exception in print_all_documents: {e}", exc_info=True)
   
    llm = ChatGoogleGenerativeAI(model=settings.LLM_MODEL, temperature=0)
    
    hitl_middleware = HumanInTheLoopMiddleware(
        interrupt_on={
                "add_to_vault": {"allowed_decisions": ["approve", "reject", "edit"]},
                "delete_from_vault": {"allowed_decisions": ["approve", "reject", "edit"]},
                "update_vault_metadata": {"allowed_decisions": ["approve", "reject", "edit"]},
                "search_vault": False  # Search remains automatic
                }
    )

    app.bot_data["agent"] = create_agent(
        model=llm,
        tools=tools, # search_docs, ingest_document, delete_document
        checkpointer=MemorySaver(),
        middleware=[hitl_middleware],
        system_prompt=settings.SYSTEM_PROMPT
    )

async def on_shutdown(app: Application):
    logger.info("Shutting down application and closing vector store.")  # [LOG]
    logger.info("==== BOT SESSION END ====" + "\n")  # [SESSION MARKER]
    await app.bot_data["vs"].close()

async def start(update, context):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    logger.info(f"/start command received from user_id={user_id}, chat_id={chat_id}")  # [LOG]
    try:
        if user_id!=settings.AUTHORIZED_ID:
            logger.warning(f"Unauthorized access attempt by user_id={user_id}, chat_id={chat_id}")  # [LOG]
            await update.message.reply_text("🚫 Access Denied. You are not authorized.")
            return # Stop processing the command
        await update.message.reply_text("Welcome back, authorized user!")
    except Exception as e:
        logger.error(f"Exception in start handler: {e}", exc_info=True)  # [ERROR LOG]

async def handle_ingest_qdrant(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    logger.info(f"Ingest command received from user_id={user_id}, chat_id={chat_id}, args={context.args}")  # [LOG]
    try:
        doc = " ".join(context.args[1:])
        item_type = context.args[0]
        update_date = update.message.date
        metadatas = {"item_type": item_type, "update_date": update_date}
        logger.debug(f"Adding doc: {doc}, metadatas: {metadatas}")  # [LOG]
        await context.bot_data["vs"].add(texts=[doc], metadatas=[metadatas])
        logger.info("Document ingested into vector store.")  # [LOG]
    except Exception as e:
        logger.error(f"Exception in handle_ingest_qdrant: {e}", exc_info=True)  # [ERROR LOG]

async def handle_search_qdrant(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    query = " ".join(context.args)
    logger.info(f"Search command received from user_id={user_id}, chat_id={chat_id}, query='{query}'")  # [LOG]
    try:
        search_results = await context.bot_data["vs"].search(query=query, top_k=2)
        logger.debug(f"Search results: {search_results}")  # [LOG]
        text = "\n".join([doc["text"] for doc in search_results])
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text)
    except Exception as e:
        logger.error(f"Exception in handle_search_qdrant: {e}", exc_info=True)  # [ERROR LOG]

def format_agent_response(response):
    """
    Formats the agent/tool response for user-friendly Telegram output.
    Handles search (list of dicts), string, None, or empty cases for all tool actions.
    """
    if response is None:
        return "⚠️ No response from the agent. Please try again."
    if isinstance(response, str):
        text = response.strip()
        if not text:
            return "⚠️ Operation completed, but no details were returned."
        return text
    if isinstance(response, list):
        # For search: list of dicts with 'text' fields
        texts = [str(x.get("text", "")) for x in response if x.get("text")]
        if texts:
            return "\n".join(texts)
        return "ℹ️ No results found."
    # For dict or other types
    text = str(response).strip()
    if not text:
        return "⚠️ Operation completed, but no details were returned."
    return text

async def handle_agent_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    logger.info(f"[handle_agent_chat] Received message from user_id={user_id}, chat_id={chat_id}: '{update.message.text}'")
    try:
        if user_id != settings.AUTHORIZED_ID:
            logger.warning(f"[handle_agent_chat] Unauthorized user_id={user_id}, ignoring message.")
            return

        # ── AWAITING UPDATE CHANGES ──────────────────────────────────────────
        # User has confirmed the document and is now describing the changes.
        # Apply the update directly — do NOT re-invoke the agent (that causes the loop).
        if context.user_data.get("awaiting_update_changes"):
            context.user_data.pop("awaiting_update_changes")
            pending_doc = context.user_data.pop("pending_update_doc", None)
            pending_filters = context.user_data.pop("pending_update_filters", None)
            logger.info(f"[handle_agent_chat] Applying update. filters={pending_filters}, changes='{update.message.text}'")

            if not pending_filters:
                await update.message.reply_text("⚠️ Lost track of which document to update. Please start over.")
                return

            vs = context.bot_data["vs"]
            # Use the LLM to parse the user's change description into a metadata dict
            try:
                from langchain_google_genai import ChatGoogleGenerativeAI
                parse_llm = ChatGoogleGenerativeAI(model=settings.LLM_MODEL, temperature=0)
                current_meta = pending_doc.get("metadata", {}) if pending_doc else {}
                current_text = pending_doc.get("text", "") if pending_doc else ""
                parse_prompt = (
                    f"The user wants to update a document.\n"
                    f"Current document text: {current_text}\n"
                    f"Current metadata: {current_meta}\n"
                    f"User's requested changes: \"{update.message.text}\"\n\n"
                    f"Return ONLY a valid JSON object with the metadata fields that should be changed/added. "
                    f"If the user wants to change the text/content itself, include a key \"__text__\" with the new text. "
                    f"Example: {{\"status\": \"watched\", \"rating\": 9}}\n"
                    f"Do not include fields that are not being changed. Do not include any explanation."
                )
                parse_response = parse_llm.invoke(parse_prompt)
                import json, re
                raw = parse_response.content
                # Gemini may return content as a list of parts or a plain string
                if isinstance(raw, list):
                    raw = " ".join(
                        part.get("text", "") if isinstance(part, dict) else str(part)
                        for part in raw
                    )
                raw = raw.strip()
                # Extract JSON from the response
                json_match = re.search(r'\{.*\}', raw, re.DOTALL)
                new_fields = json.loads(json_match.group()) if json_match else {}
                logger.info(f"[handle_agent_chat] Parsed update fields: {new_fields}")
            except Exception as e:
                logger.error(f"[handle_agent_chat] Failed to parse update fields: {e}", exc_info=True)
                await update.message.reply_text("⚠️ Could not parse the requested changes. Please try again.")
                return

            new_text = new_fields.pop("__text__", None)
            new_metadata = new_fields  # remaining keys are metadata changes

            try:
                await vs.update_document(filter_dict=pending_filters, new_text=new_text, new_metadata=new_metadata)
                logger.info(f"[handle_agent_chat] Update applied. filters={pending_filters}, new_metadata={new_metadata}, new_text={new_text}")
                summary_lines = [f"  • {k}: {v}" for k, v in new_metadata.items()]
                if new_text:
                    summary_lines.insert(0, f"  • content: {new_text}")
                summary = "\n".join(summary_lines) or "  (no changes detected)"
                await update.message.reply_text(f"✅ Document updated successfully!\n\n<b>Changes applied:</b>\n{summary}", parse_mode="HTML")
            except Exception as e:
                logger.error(f"[handle_agent_chat] Update failed: {e}", exc_info=True)
                await update.message.reply_text(f"❌ Update failed: {e}")
            return

        # ── REFINING UPDATE SEARCH ───────────────────────────────────────────
        # User is clarifying which document to search for — normal agent flow.
        if context.user_data.get("refining_update_search"):
            logger.info("[handle_agent_chat] User refining update document search.")
            context.user_data.pop("refining_update_search")
            # Fall through to normal agent invoke below
        config = {
            "configurable": {
                "thread_id": str(chat_id),
                "vs": context.bot_data["vs"] 
            }
        }    
        agent = context.bot_data["agent"]
        logger.info(f"[handle_agent_chat] Agent dir: {dir(agent)}")
        logger.info(f"[handle_agent_chat] Agent tool_map: {getattr(agent, 'tool_map', 'N/A')}")
        logger.debug(f"[handle_agent_chat] Invoking agent with config: {config} and message: {update.message.text}")
        logger.info(f"[handle_agent_chat] LLM invocation input: messages={[('user', update.message.text)]}, config={config}")
        result = agent.invoke({"messages": [("user", update.message.text)]}, config)
        logger.info(f"[handle_agent_chat] LLM invocation result: {result}")
        logger.debug(f"[handle_agent_chat] Agent result: {result}")
        # --- DEBUG: Print the full result structure for HITL troubleshooting ---
        logger.info(f"[handle_agent_chat] DEBUG: Full agent result type={type(result)}, dir={dir(result)}, as_dict={getattr(result, '__dict__', str(result))}")
        # --- END DEBUG ---
        # Robust interrupt detection: check for attribute, dict key, or list
        interrupt = False
        if hasattr(result, "__interrupt__") and getattr(result, "__interrupt__", None):
            interrupt = True
        elif isinstance(result, dict) and "__interrupt__" in result and result["__interrupt__"]:
            interrupt = True
        # Optionally, check for other forms if needed
        if interrupt:
            logger.info("[handle_agent_chat] Agent action requires approval (HITL interrupt). Sending approval UI.")
            action_requests = None
            interrupt_obj = None
            if hasattr(result, "__interrupt__"):
                interrupt_obj = getattr(result, "__interrupt__", [])[0]
            elif isinstance(result, dict):
                interrupt_obj = result["__interrupt__"][0]
            # Interrupt may be a custom class, so use vars() or __dict__
            if interrupt_obj is not None:
                # Try dict-style first
                if isinstance(interrupt_obj, dict):
                    action_requests = interrupt_obj.get("value", {}).get("action_requests", [])
                else:
                    # Try attribute or __dict__
                    value = getattr(interrupt_obj, "value", None)
                    if value is None and hasattr(interrupt_obj, "__dict__"):
                        value = interrupt_obj.__dict__.get("value", None)
                    if value and isinstance(value, dict):
                        action_requests = value.get("action_requests", [])
            if action_requests:
                action_name = action_requests[0].get("name", "")
                args = action_requests[0].get("args", {})

                if action_name == "add_to_vault":
                    doc_text = args.get("text", "")
                    metadata = args.get("metadata", {})
                    details = []
                    if doc_text:
                        details.append(f"<b>Content:</b> {doc_text}")
                    if metadata:
                        meta_lines = "\n".join(f"  • {k}: {v}" for k, v in metadata.items())
                        details.append(f"<b>Metadata:</b>\n{meta_lines}")
                    details_str = "\n".join(details)
                    confirm_text = f"📝 Are you sure you want to add this item to your vault?\n\n{details_str}"
                    keyboard = [
                        [InlineKeyboardButton("✅ Approve", callback_data="approve"),
                         InlineKeyboardButton("🔄 Retry", callback_data="reject_and_retry")],
                        [InlineKeyboardButton("📝 Edit", callback_data="edit"),
                         InlineKeyboardButton("❌ Abort", callback_data="abort")]
                    ]

                elif action_name == "delete_from_vault":
                    filters = args.get("filters", {})
                    filter_lines = "\n".join(f"  • {k}: {v}" for k, v in filters.items())
                    confirm_text = f"⚠️ Are you sure you want to delete item(s) matching:\n\n{filter_lines}"
                    keyboard = [
                        [InlineKeyboardButton("✅ Approve", callback_data="approve"),
                         InlineKeyboardButton("🔄 Retry", callback_data="reject_and_retry")],
                        [InlineKeyboardButton("📝 Edit", callback_data="edit"),
                         InlineKeyboardButton("❌ Abort", callback_data="abort")]
                    ]

                elif action_name == "update_vault_metadata":
                    filters = args.get("filters", {})
                    proposed_new_metadata = dict(args.get("new_metadata", {}))
                    # Look up the actual document to display its content and metadata
                    vs = context.bot_data.get("vs")
                    doc_display = ""
                    if vs and filters:
                        try:
                            doc_id = filters.get("id") or filters.get("_id")
                            if doc_id:
                                results = await vs.search(query="", filter_dict={"id": doc_id}, top_k=1)
                            else:
                                results = await vs.search(
                                    query=" ".join(str(v) for v in filters.values()),
                                    filter_dict=filters, top_k=1
                                )
                            if results:
                                found_doc = results[0]
                                # ── CURRENT version ──────────────────────────
                                doc_text = found_doc.get("text", "")
                                meta = {k: v for k, v in found_doc.get("metadata", {}).items()
                                        if k not in ("_id", "_collection_name", "version",
                                                     "creation_datetime", "update_datetime", "id")}
                                meta_lines = "\n".join(f"  • {k}: {v}" for k, v in meta.items())
                                current_block = f"<b>📄 Content:</b> {doc_text}\n<b>🏷 Metadata:</b>\n{meta_lines}"

                                # ── PROPOSED new version ─────────────────────
                                new_text_proposed = proposed_new_metadata.pop("text", None)  # agent uses "text" for content
                                new_meta_proposed = {k: v for k, v in proposed_new_metadata.items()
                                                     if k not in ("_id", "_collection_name", "version",
                                                                  "creation_datetime", "update_datetime", "id", "__text__")}
                                new_block_lines = []
                                new_block_lines.append(f"  📄 Content: {new_text_proposed if new_text_proposed else doc_text}")
                                merged_meta = {**meta, **new_meta_proposed}
                                for k, v in merged_meta.items():
                                    old_v = meta.get(k)
                                    if k in new_meta_proposed and str(old_v) != str(v):
                                        new_block_lines.append(f"  🏷 {k}: <s>{old_v}</s> → <b>{v}</b>")
                                    else:
                                        new_block_lines.append(f"  🏷 {k}: {v}")
                                new_block = "\n".join(new_block_lines)

                                doc_display = (
                                    f"<b>Before:</b>\n{current_block}\n\n"
                                    f"<b>After:</b>\n{new_block}"
                                )

                                # Restore "text" into proposed_new_metadata as "__text__" for the update step
                                if new_text_proposed:
                                    proposed_new_metadata["__text__"] = new_text_proposed

                                # Store for use after user clicks Confirm
                                context.user_data["pending_update_doc"] = found_doc
                                context.user_data["pending_update_filters"] = filters
                                context.user_data["pending_update_new_metadata"] = proposed_new_metadata
                                logger.info(f"[handle_agent_chat] Update preview fetched: {found_doc}, proposed new_metadata={proposed_new_metadata}")
                            else:
                                doc_display = f"<b>Filters used:</b> {filters}\n(Document not found with these filters)"
                        except Exception as e:
                            logger.warning(f"[handle_agent_chat] Could not fetch document for update preview: {e}")
                            doc_display = f"<b>Filters:</b> {filters}"
                    else:
                        doc_display = f"<b>Filters:</b> {filters}"

                    confirm_text = f"✏️ Approve this update?\n\n{doc_display}"
                    keyboard = [
                        [InlineKeyboardButton("✅ Approve", callback_data="confirm_update"),
                         InlineKeyboardButton("🔍 Another Document", callback_data="refine_update")],
                        [InlineKeyboardButton("❌ Abort", callback_data="abort_update")]
                    ]

                else:
                    details_str = str(args)
                    confirm_text = f"⚠️ Action requires approval:\n\n{details_str}"
                    keyboard = [
                        [InlineKeyboardButton("✅ Approve", callback_data="approve"),
                         InlineKeyboardButton("🔄 Retry", callback_data="reject_and_retry")],
                        [InlineKeyboardButton("📝 Edit", callback_data="edit"),
                         InlineKeyboardButton("❌ Abort", callback_data="abort")]
                    ]
            else:
                confirm_text = "⚠️ Action requires approval."
                keyboard = [
                    [InlineKeyboardButton("✅ Approve", callback_data="approve"),
                     InlineKeyboardButton("🔄 Retry", callback_data="reject_and_retry")],
                    [InlineKeyboardButton("📝 Edit", callback_data="edit"),
                     InlineKeyboardButton("❌ Abort", callback_data="abort")]
                ]
            await update.message.reply_text(confirm_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
            logger.debug("[handle_agent_chat] Approval UI sent to user.")
            return  # Prevent sending a normal response when approval is required
        else:
            logger.info("[handle_agent_chat] Agent completed without HITL. Sending response to user.")
            content = result["messages"][-1].content
            reply_text = format_agent_response(content)
            if not reply_text.strip():
                reply_text = "⚠️ Operation completed, but no details were returned."
            await update.message.reply_text(reply_text)
            logger.debug(f"[handle_agent_chat] Sent message: {reply_text}")
    except Exception as e:
        logger.error(f"[handle_agent_chat] Exception: {e}", exc_info=True)  # [ERROR LOG]

async def handle_callback(update, context):
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat.id
    logger.info(f"[handle_callback] Callback query received from user_id={user_id}, chat_id={chat_id}: {query.data}")
    try:
        try:
            await query.answer()
        except Exception as answer_err:
            logger.warning(f"[handle_callback] query.answer() failed (stale/duplicate callback, ignoring): {answer_err}")
            return  # Stale callback — nothing to do
        # Handle abort directly, do not call agent.invoke
        if query.data == "abort":
            await query.edit_message_text("❌ Action aborted. No changes were made.")
            logger.info("[handle_callback] User aborted the action. Notified user and skipped agent.invoke.")
            return
        # Handle update flow callbacks
        if query.data == "abort_update":
            # Resume the interrupted thread cleanly before aborting
            config = {
                "configurable": {
                    "thread_id": str(chat_id),
                    "vs": context.bot_data["vs"]
                }
            }
            try:
                context.bot_data["agent"].invoke(
                    Command(resume={"decisions": [{"type": "reject", "message": "User aborted the update."}]}),
                    config=config
                )
            except Exception as e:
                logger.warning(f"[handle_callback] abort_update: agent resume failed (non-fatal): {e}")
            await query.edit_message_text("❌ Update cancelled. No changes were made.")
            logger.info("[handle_callback] User aborted the update. Notified user.")
            context.user_data.pop("pending_update_doc", None)
            context.user_data.pop("pending_update_filters", None)
            return
        if query.data == "confirm_update":
            # Resume the agent with a reject decision so the LangGraph thread finishes cleanly.
            config = {
                "configurable": {
                    "thread_id": str(chat_id),
                    "vs": context.bot_data["vs"]
                }
            }
            try:
                context.bot_data["agent"].invoke(
                    Command(resume={"decisions": [{"type": "reject", "message": "User will describe changes separately."}]}),
                    config=config
                )
            except Exception as e:
                logger.warning(f"[handle_callback] confirm_update: agent resume failed (non-fatal): {e}")

            pending_doc = context.user_data.get("pending_update_doc")
            pending_filters = context.user_data.get("pending_update_filters")
            pending_new_metadata = context.user_data.pop("pending_update_new_metadata", {})

            # Normalize: agent may put new text under "text" key — move it to "__text__"
            if "text" in pending_new_metadata and not pending_new_metadata.get("__text__"):
                pending_new_metadata["__text__"] = pending_new_metadata.pop("text")

            if pending_new_metadata and pending_filters:
                # Agent already knows what to change — apply directly without asking again
                vs = context.bot_data["vs"]
                new_text = pending_new_metadata.pop("__text__", None)
                new_metadata = pending_new_metadata
                try:
                    await vs.update_document(filter_dict=pending_filters, new_text=new_text, new_metadata=new_metadata)
                except Exception as e:
                    logger.error(f"[handle_callback] confirm_update: direct update failed: {e}", exc_info=True)
                    await query.edit_message_text(f"❌ Update failed: {e}")
                    context.user_data.pop("pending_update_doc", None)
                    context.user_data.pop("pending_update_filters", None)
                    return

                summary_lines = [f"  • {k}: {v}" for k, v in new_metadata.items()]
                if new_text:
                    summary_lines.insert(0, f"  • content: {new_text}")
                summary = "\n".join(summary_lines) or "  (no changes)"
                await query.edit_message_text(f"✅ Document updated successfully!\n\n<b>Changes applied:</b>\n{summary}", parse_mode="HTML")
                logger.info(f"[handle_callback] confirm_update: applied proposed changes directly. filters={pending_filters}, new_text={new_text}, new_metadata={new_metadata}")
                context.user_data.pop("pending_update_doc", None)
                context.user_data.pop("pending_update_filters", None)
            else:
                # Agent did not know what to change — ask the user to describe
                await query.edit_message_text("✏️ Please describe what changes you'd like to make to this document.")
                logger.info("[handle_callback] confirm_update: no proposed changes, asking user.")
                context.user_data["awaiting_update_changes"] = True
            return
        if query.data == "refine_update":
            await query.edit_message_text("🔍 Please provide more details about which document you need:\n- Use natural language\n- Or specify metadata fields (e.g., 'task with status=done')")
            logger.info("[handle_callback] User requested document refinement. Waiting for clarification.")
            context.user_data["refining_update_search"] = True
            return
        config = {
            "configurable": {
                "thread_id": str(chat_id), 
                "vs": context.bot_data["vs"]
            }
        }
        decision = [{"type": query.data}] # approve, reject_and_retry, etc.
        logger.debug(f"[handle_callback] Resuming agent with decision: {decision} and config: {config}")
        final_result = context.bot_data["agent"].invoke(
            Command(resume={"decisions": decision}), 
            config=config
        )
        logger.debug(f"[handle_callback] Agent final result after callback: {final_result}")
        # After approval, send confirmation for add/delete
        if query.data == "approve":
            # Try to infer action type from final_result
            last_tool_call = None
            for msg in final_result["messages"]:
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    last_tool_call = msg.tool_calls[-1]
            if last_tool_call:
                action_name = last_tool_call.get("name", "")
                if action_name == "add_to_vault":
                    confirmation = "✅ Item successfully added to your vault."
                elif action_name == "delete_from_vault":
                    confirmation = "🗑️ Item(s) successfully deleted from your vault."
                else:
                    confirmation = format_agent_response(final_result["messages"][-1].content)
            else:
                confirmation = format_agent_response(final_result["messages"][-1].content)
            # Only edit if the message content is different
            if query.message.text != confirmation:
                await query.edit_message_text(confirmation)
                logger.info(f"[handle_callback] Sent final agent message to user: {confirmation}")
            else:
                logger.info(f"[handle_callback] Skipped edit_message_text: content unchanged.")
        else:
            new_text = format_agent_response(final_result["messages"][-1].content)
            if query.message.text != new_text:
                await query.edit_message_text(new_text)
                logger.info(f"[handle_callback] Sent final agent message to user: {new_text}")
            else:
                logger.info(f"[handle_callback] Skipped edit_message_text: content unchanged.")
    except Exception as e:
        logger.error(f"[handle_callback] Exception: {e}", exc_info=True)  # [ERROR LOG]


if __name__ == "__main__":
    application = ApplicationBuilder().token(settings.TELEGRAM_TOKEN).post_init(on_startup).post_shutdown(on_shutdown).build()


    application.add_handler(CommandHandler("start", start))
    # application.add_handler(CommandHandler(["add", "ingest"], handle_ingest_qdrant))
    # application.add_handler(CommandHandler(["search", "find"], handle_search_qdrant))

    # Agent Handlers
    application.add_handler(CallbackQueryHandler(handle_callback))
    # This handler catches all text that isn't a command and sends it to the agent
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_agent_chat))


    application.run_polling()


