# AI Telegram Bot with OpenAI Integration

A sophisticated Telegram bot integrated with OpenAI's GPT-4o model, featuring chat history management, automated status reporting, and log maintenance.

## Features

- **OpenAI Integration**: Powered by GPT-4o for intelligent and friendly responses.
- **Context Awareness**: Maintains chat history (last 10 messages) for coherent conversations.
- **Session Management**: Easily start new chat sessions using the "Start new chat" button.
- **Admin Dashboard**: Periodic status reports sent to the administrator, including request stats and system health.
- **Auto Log Maintenance**: Automatic cleaning of log files when they exceed size limits.
- **Statistics**: Built-in command to check bot usage statistics.

## Prerequisites

- Python 3.10 or higher
- OpenAI API Key
- Telegram Bot Token (from [@BotFather](https://t.me/BotFather))
- Admin Chat ID (for receiving status reports)

## Installation

1.  **Clone the repository**:
    ```bash
    git clone <repository-url>
    cd chat-gpt-telegram-bot
    ```

2.  **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

3.  **Configure environment variables**:
    Create a `.env` file in the root directory and add the following:
    ```env
    OPENAI_API_KEY=your_openai_api_key
    TELEGRAM_TOKEN=your_telegram_bot_token
    ADMIN_CHAT_ID=your_admin_chat_id
    ```

## Usage

Start the bot by running:
```bash
python main.py
```

### Bot Commands
- `/start`: Initialize the bot and receive a welcome message.
- `/stats`: View usage statistics (total requests and errors).

### Interactive Menu
- **Start new chat**: Clears current history and starts a fresh conversation.

## System Maintenance

- **Status Reports**: The bot sends a detailed health report to the admin daily at 9:00 AM and 9:00 PM (Asia/Tashkent).
- **Log Cleaning**: Log file size is checked daily at midnight. If it exceeds 10MB, the older half of the logs is removed to save space.

## License

This project is licensed under the [LGPL-3.0](LICENSE).
