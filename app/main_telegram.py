import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, Application, CommandHandler, ContextTypes
from app.models.embedding_model import StubEmbeddingModel, GeminiEmbeddingModel
from app.vector_store import QdrantStore

from app.config import settings


logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)


async def on_startup(app: Application):
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

async def on_shutdown(app: Application):
    await app.bot_data["vs"].close()

async def start(update, context):
    user_id = update.effective_user.id
    
    if user_id==settings.AUTHORIZED_ID:
        await update.message.reply_text("🚫 Access Denied. You are not authorized.")
        return # Stop processing the command

    await update.message.reply_text("Welcome back, authorized user!")

async def handle_ingest_qdrant(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"\n\n\nuser id: {update.effective_user.id}\n\n\n")
    doc = " ".join(context.args[1:])
    item_type = context.args[0]
    update_date = update.message.date
    metadatas = {"item_type": item_type, "update_date": update_date}
    await context.bot_data["vs"].add(texts=[doc], metadatas=[metadatas])

async def handle_search_qdrant(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)
    search_results = await context.bot_data["vs"].search(query=query, top_k=2)
    text = "\n".join([doc["text"] for doc in search_results])
    await context.bot.send_message(chat_id=update.effective_chat.id, text=text)








if __name__ == "__main__":
    application = ApplicationBuilder().token(settings.TELEGRAM_TOKEN).post_init(on_startup).post_shutdown(on_shutdown).build()

    ingest_handler = CommandHandler(["add", "ingest"], handle_ingest_qdrant)
    search_handler = CommandHandler(["search", "find"], handle_search_qdrant)

    application.add_handler(CommandHandler("start", start))
    application.add_handler(ingest_handler)
    application.add_handler(search_handler)


    application.run_polling()


