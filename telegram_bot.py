import base64
import configparser
import html
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import requests
from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    KeyboardButton,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

# Read configuration file
config = configparser.RawConfigParser()
config.read("config.ini")

# Get Open Monitoring Distribution (OMD) site
omd_site = config["check_mk"]["site"]
omd_site_dir = f"/omd/sites/{omd_site}"

# Append path for Check_MK LiveStatus API for Python
sys.path.append(f"{omd_site_dir}/share/doc/check_mk/livestatus/api/python")
import livestatus

logger = logging.getLogger(__name__)
formatter = logging.Formatter(
    "%(asctime)s:%(levelname)s:%(funcName)s:%(message)s"
)

log_file_path = os.path.join("/", "var", "log", "telegram-plus.log")
log_file_handler = logging.FileHandler(log_file_path, mode="a")
log_file_handler.setLevel(logging.DEBUG)
log_file_handler.setFormatter(formatter)
logger.addHandler(log_file_handler)

# Get Telegram Bot API token from configuration file
telegram_bot_token = config["telegram_bot"]["api_token"]

# Define constants for conversation handler
HOSTGROUP, HOSTNAME, SERVICE, PW, NOTIFICATION_SETTING = range(5)

# Save the home menu in a variable so that it can be reused in
# several locations later.
home_menu = ReplyKeyboardMarkup(
    [
        [
            KeyboardButton(text="⭕ GET HOST STATUS"),
            KeyboardButton(text="📃 GET SERVICES OF HOST"),
        ],
        [
            KeyboardButton(text="🔍 GET SERVICE DETAILS"),
            KeyboardButton(text="🔥 GET ALL HOST PROBLEMS"),
        ],
        [
            KeyboardButton(text="❗ GET ALL SERVICE PROBLEMS"),
            KeyboardButton(text="🔔 NOTIFICATION SETTINGS"),
        ],
        [KeyboardButton(text="📉 GET SERVICE GRAPHS")],
    ],
    resize_keyboard=False,
    one_time_keyboard=True,
    input_field_placeholder="Choose an option",
)

# Set path of LiveStatus socket
livestatus_socket_path = f"unix:{omd_site_dir}/tmp/run/live"

# Create LiveStatus connection
livestatus_connection = livestatus.SingleSiteConnection(livestatus_socket_path)

# Set path of query for notifications
notify_query_path = f"{omd_site_dir}/tmp/telegram_plus"


# Function to set bot commands
async def post_init(bot_handler: Application) -> None:
    bot = bot_handler.bot
    await bot.set_my_commands(
        [
            BotCommand("start", "Start a chat with the bot"),
            BotCommand("help", "Get help"),
            BotCommand("menu", "Update the menu"),
            BotCommand("cancel", "Cancel a conversation"),
            BotCommand("authenticate", "Verify yourself to the bot"),
        ]
    )


# Build bot application
bot_handler = (
    Application.builder()
    .token(telegram_bot_token)
    .post_init(post_init)
    .arbitrary_callback_data(True)
    .build()
)

# Get job queue of bot
bot_handler_job_queue = bot_handler.job_queue


class NotifyHandler(FileSystemEventHandler):
    # Method to be called when a file is created
    def on_created(self, event):
        # Get the file path
        file_path = event.src_path

        # Check if the path is a file and not a folder
        if os.path.isfile(file_path):
            try:
                # Run the send_automatic_notification method
                # The method is executed with run_once so that the message can
                # be processed based on the Telegram bot queue and no
                # problems occur
                bot_handler_job_queue.run_once(
                    send_automatic_notification, 3, data=file_path
                )
            # Handle potential exceptions
            except Exception as e:
                logger.critical(e)


def log_authenticated_access(username, command):
    logger.info(f"{username} has executed the command '{command}'")


def log_unauthenticated_access(username, command):
    logger.warning(
        f"{username} tried to execute the command '{command}' "
        "but was not authorised to do so!"
    )


# Method to check if a user is authenticated
def is_user_authenticated(user_id):
    # Read the config file again so that no information is missing.
    config.read("config.ini")

    # Check if the user is in the allowed_users list
    if str(user_id) in config["telegram_bot"]["allowed_users"]:
        return True
    else:
        False


# Method to get the state "details"
def get_state_details(val):
    if val == 0 or val == "OK" or val == "UP":
        return "✅", "OK"
    if val == 1 or val == "WARN":
        return "⚠️", "WARN"
    if val == 2 or val == "CRIT" or val == "DOWN":
        return "🛑", "CRIT"
    if val == 3 or val == "UNKN":
        return "🟠", "UNKNOWN"
    else:
        return "", "???"


# Method to initially start the conversation with the bot
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Get the userdetails
    user = update.effective_user

    # Check if the user is authenticated
    if is_user_authenticated(user.id):
        # Send message to the user with the home menu
        await update.message.reply_text(
            f"Hi! {user.username} 👋. I have added a menu to your keyboard ⌨️,"
            "which you can use to interact with me. If you don't see it, type "
            "/menu. If you need help just try /help",
            reply_markup=home_menu,
        )
        log_authenticated_access(user.username, "/start")
    else:
        # Send error message to the user if not authenticated
        await update.message.reply_text(
            "You are not authenticated! 🔐 When using the bot for the first "
            "time, you must authenticate yourself with a password. If you do "
            "not do this, the bot 🤖 will not respond to any of your "
            "further requests."
        )
        log_unauthenticated_access(user.username, "/start")


# Method to show help
async def help_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    # Check if the user is authenticated
    if is_user_authenticated(update.effective_user.id):
        # Send help message
        # Still needs to be written lol
        await update.message.reply_text("Help!")
        log_authenticated_access(update.effective_user.username, "/help")
    else:
        log_unauthenticated_access(update.effective_user.username, "/help")


# Method to get the host name
async def get_host_name(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    # Initialize hosts list
    hosts = []

    # Try to get the data from the livestatus connection & sort them
    try:
        for host in sorted(
            livestatus_connection.query_table(
                "GET hostsbygroup\n"
                f"Filter: hostgroup_name = {update.message.text}\n"
                "Columns: name"
            ),
            key=lambda d: d[0],
        ):
            hosts.append(KeyboardButton(text=str(host[0])))

        await update.message.reply_text(
            "PLEASE TELL ME THE HOSTNAME",
            reply_markup=ReplyKeyboardMarkup.from_column(
                hosts,
                resize_keyboard=False,
                one_time_keyboard=True,
                input_field_placeholder="SELECT A HOST IN THE MENU",
            ),
        )

    except Exception as e:
        logger.critical(e)
        await update.message.reply_text(
            "I'm sorry but while I was processing your request an "
            "error occurred!",
            reply_markup=home_menu,
        )

    return HOSTNAME


# Method to get the host group name
async def get_host_group(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    # Check if the user is authenticated
    if is_user_authenticated(update.effective_user.id):
        hostgroups = []

        try:
            # Get the list of hostgroups from livestatus connection
            # and sort them
            for hostgroup in sorted(
                livestatus_connection.query_table(
                    "GET hostgroups\nColumns: name\n"
                ),
                key=lambda d: d[0],
            ):
                # Append each hostgroup to the hostgroups list
                hostgroups.append(KeyboardButton(text=str(hostgroup[0])))

            # Reply to the message with the list of hostgroups in the form
            # a ReplyKeyboardMarkup and prompt the user to select one
            # of these
            await update.message.reply_text(
                "PLEASE TELL ME THE HOSTGROUP OF THE HOST",
                reply_markup=ReplyKeyboardMarkup.from_column(
                    hostgroups,
                    resize_keyboard=False,
                    one_time_keyboard=True,
                    input_field_placeholder="SELECT A HOSTGROUP IN THE MENU",
                ),
            )
            log_authenticated_access(
                update.effective_user.username, "⭕ GET HOST STATUS"
            )

        # Catch any exception that may occur
        except Exception as e:
            logger.critical(e)
            await update.message.reply_text(
                "I'm sorry but while I was processing your request an "
                "error occurred!"
            )

        return HOSTGROUP
    else:
        log_unauthenticated_access(
            update.effective_user.username, "⭕ GET HOST STATUS"
        )


# Method to get the service name
async def get_service_name(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    services = []

    try:
        # Get list of services from livestatus connection and sort
        # by description
        for description, state in sorted(
            livestatus_connection.query_table(
                "GET services\n"
                f"Filter: host_name = {update.message.text}\n"
                "Columns: description state\n"
            ),
            key=lambda d: d[0],
        ):
            # Append the service to services list
            services.append(f"{update.message.text} / {description}")

        # Reply to the message with the list of services in the form
        # a ReplyKeyboardMarkup and prompt the user to select one
        # of these
        await update.message.reply_text(
            "PLEASE TELL ME THE SERVICE NAME",
            reply_markup=ReplyKeyboardMarkup.from_column(
                services,
                resize_keyboard=False,
                one_time_keyboard=True,
                input_field_placeholder="SELECT A SERVICE IN THE MENU",
            ),
        )

    # Catch any errors
    except Exception as e:
        logger.critical(e)
        await update.message.reply_text(
            "I'm sorry but while I was processing your request an "
            "error occurred!",
            reply_markup=home_menu,
        )

    return SERVICE


def get_host_status(hostname):
    # Get the status of a host
    host = livestatus_connection.query_table(
        f"GET hosts\nFilter: name = {hostname}\nColumns: state"
    )
    state = f"{hostname} IS "
    state += "ONLINE ✅" if host[0][0] == 0 else "<u><b>OFFLINE</b></u> 🛑"

    return state


async def print_host_status(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    try:
        # Reply to the user with the current status of the host
        state = get_host_status(update.message.text)
        await update.message.reply_html(
            state,
            reply_markup=home_menu,
        )

    except Exception as e:
        logger.critical(e)
        await update.message.reply_text(
            "I'm sorry but while I was processing your request an "
            "error occurred!",
            reply_markup=home_menu,
        )

    return ConversationHandler.END


async def get_services(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    services = f"<u><b>{update.message.text}:</b></u>\n\n"

    try:
        # Get list of services from livestatus connection and sort
        # by description
        for description, state in sorted(
            livestatus_connection.query_table(
                "GET services\n"
                f"Filter: host_name = {update.message.text}\n"
                "Columns: description state\n"
            ),
            key=lambda d: d[0],
        ):
            state_emoji, state_text = get_state_details(state)
            services += f"{state_emoji} {description} - {state_text}\n"

        # Reply to the message with the list of services in the form
        # a ReplyKeyboardMarkup and prompt the user to select one
        # of these
        await update.message.reply_html(
            services,
            reply_markup=home_menu,
        )

    except Exception as e:
        logger.critical(e)
        await update.message.reply_text(
            "I'm sorry but while I was processing your request an "
            "error occurred!",
            reply_markup=home_menu,
        )

    return ConversationHandler.END


def get_service_details(hostname, servicename):
    # Get list of services from livestatus connection using filters and
    # specific columns
    service = livestatus_connection.query_table(
        "GET services\n"
        f"Filter: host_name = {hostname}\n"
        f"Filter: description = {servicename}\n"
        "Columns: "
        "description "
        "state perf_data "
        "plugin_output "
        "long_plugin_output "
        "last_check "
    )

    # Get the state details for the service using the state value from the
    # service list
    state_emoji, state_text = get_state_details(service[0][1])

    # Create a details string with the service state, hostname, service name,
    # summary, details, metrics, and info
    details = (
        f"{state_emoji} <u><b>{hostname} / {servicename} - "
        f"{state_text}</b></u>\n\n"
        f"<b>SUMMARY: </b>\n"
        f"<code><pre>{html.escape(service[0][3])}</pre></code>\n\n"
        f"<b>DETAILS: </b>\n"
        f"<code><pre>{html.escape(service[0][4])}</pre></code>\n\n"
        "<b>METRICS: </b>\n"
    )

    # Add any available metrics to the details string
    if len(service[0][2]) > 1:
        for metric in service[0][2].split(" "):
            if "=" in metric:
                name, values = metric.split("=")
                value, warn, crit, min, max = values.split(";")
                details += f"{name}: {value}\n"
    else:
        details += "No metrics available\n"

    # Add last check time to the details string
    details += (
        "\n<b>INFO: </b>\n"
        f"Last Check: {datetime.fromtimestamp(service[0][5])}"
    )

    return details


async def print_service_details(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    # Get hostname and service name from the message text
    hostname, service = update.message.text.split(" / ")

    try:
        # Get the service details and reply with the details using HTML
        details = get_service_details(hostname, service)
        await update.message.reply_html(
            details,
            reply_markup=home_menu,
        )

    except Exception as e:
        # If an error occurs, print the error and reply with an error message
        logger.critical(e)
        await update.message.reply_text(
            "I'm sorry but while I was processing your request an "
            "error occurred!",
            reply_markup=home_menu,
        )

    return ConversationHandler.END


def get_service_graphs(hostname, service):
    # Construct URL to request graphs of the specified service on the
    # specified host
    url = (
        f"http://localhost:80/{omd_site}/check_mk/ajax_graph_images.py?"
        f"host={hostname}&"
        f"service={service}"
    )

    # Send a GET request to the constructed URL and retrieve the response
    response = requests.get(url, allow_redirects=True, verify=False)

    # Raise an exception if there was an HTTP error
    response.raise_for_status()

    # Parse the JSON response into a list of base64-encoded strings
    # representing images
    jsonResponse = response.json()

    # Create a list of InputMediaPhoto objects from the decoded images
    graphs = []
    for graph in [base64.b64decode(s) for s in jsonResponse]:
        graphs.append(InputMediaPhoto(graph))

    # Split the graphs into groups of 10 or fewer, since Telegram's API has a
    # limit on the number of media items per message
    max_media_chunk_size = 10
    chucked_graphs = []
    for i in range(0, len(graphs), max_media_chunk_size):
        chucked_graphs.append(graphs[i : i + max_media_chunk_size])

    # Return the chunked graphs
    return chucked_graphs


async def print_service_graphs(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    # Extract hostname and service from user's message
    hostname, service = update.message.text.split(" / ")

    try:
        # Reply to the user that we are processing their request
        await update.message.reply_html(
            f"<u><b>📉 {service} GRAPH(s) FROM {hostname}</b></u>:\n"
            "This may take a second.",
            reply_markup=home_menu,
        )

        # Get the graphs for the specified service on the specified host
        graphs = get_service_graphs(hostname, service)

        # Reply to the user with the graphs, chunked into groups of 10
        for chunk in graphs:
            await update.message.reply_media_group(media=chunk)

    except Exception as e:
        # If an error occurs, print the error and reply with an error message
        print(e)
        logger.critical(e)
        await update.message.reply_text(
            "I'm sorry but while I was processing your request an "
            "error occurred! (Maybe this service has no Graphs)",
            reply_markup=home_menu,
        )

    # End the conversation handler
    return ConversationHandler.END


async def get_host_problems(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    try:
        # Query the livestatus connection to get a list of hosts that are in
        # a problematic state and belong to the group specified in the
        # user's message. The resulting list is sorted by host name.
        host_problems_array = sorted(
            livestatus_connection.query_table(
                "GET hostsbygroup\n"
                "Filter: state = 1\n"  # filter for hosts with a state of warn
                "Filter: state = 2\n"  # filter for hosts with a state of crit
                "Filter: state = 3\n"  # filter for hosts with a state of unkn
                "Or: 3\n"  # combine the three filters above with a logical OR
                f"Filter: hostgroup_name = {update.message.text}\n"
                "Columns: name state"  # only return the host name and state
            ),
            key=lambda d: d[1],
            reverse=True,
        )

        # Create a string to store the host problems and their states.
        # This string is formatted as HTML for rendering purposes.
        host_problems = (
            f"<u><b>HOST PROBLEMS ({len(host_problems_array)}):</b></u>\n\n"
        )

        # Loop through the list of hosts and their states, and append each one
        # to the host_problems string.
        for host, state in host_problems_array:
            state_emoji, state_text = get_state_details(state)
            host_problems += f"{state_emoji} {host}\n"

        # Send the host_problems string as a message reply to the user.
        # The message is formatted as HTML and includes a custom keyboard.
        await update.message.reply_html(
            host_problems,
            reply_markup=home_menu,
        )

    except Exception as e:
        # If an error occurs while processing the user's request, catch
        # the exception and send an error message to the user.
        logger.critical(e)
        await update.message.reply_text(
            "I'm sorry but while I was processing your request an "
            "error occurred!",
            reply_markup=home_menu,
        )

    # End the conversation by returning ConversationHandler.END
    return ConversationHandler.END


async def get_service_problems(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:

    try:
        # Get list of services from livestatus connection and sort
        # by description
        service_problems_array = sorted(
            livestatus_connection.query_table(
                "GET servicesbyhostgroup\n"
                "Filter: state = 1\n"
                "Filter: state = 2\n"
                "Filter: state = 3\n"
                "Or: 3\n"
                f"Filter: hostgroup_name = {update.message.text}\n"
                "Columns: host_name description state\n"
            ),
            key=lambda d: d[2],
            reverse=True,
        )

        service_problems = (
            "<u><b>SERVICE PROBLEMS "
            f"({len(service_problems_array)}):</b></u>\n\n"
        )

        # Loop through the service problems array and add each service's
        # status and description to the reply message
        for host_name, service, state in service_problems_array:
            state_emoji, state_text = get_state_details(state)
            service_problems += f"{state_emoji}<b>{host_name}</b>: {service}\n"

        # Send the reply message as HTML with the home menu as the reply markup
        await update.message.reply_html(
            service_problems,
            reply_markup=home_menu,
        )

    except Exception as e:
        logger.critical(e)
        # Send an error message with the home menu as the reply markup
        await update.message.reply_text(
            "I'm sorry but while I was processing your request an "
            "error occurred!",
            reply_markup=home_menu,
        )

    # End the conversation
    return ConversationHandler.END


async def get_pw(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Check if the user is not already authenticated
    if not is_user_authenticated(update.effective_user.id):
        # If the user is not authenticated ask for the password
        await update.message.reply_text("What is the password?!")
        return PW
    else:
        # If user is already authenticated, end the conversation
        await update.message.reply_text(
            "You are already authenticated. ✅ The process has been cancelled."
        )
        return ConversationHandler.END


async def try_to_authenticate(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    user = update.effective_user
    password = config["telegram_bot"]["password_for_authentication"]

    # Check if the password entered by the user matches the config password
    if update.message.text == password:
        allowed_users = config["telegram_bot"]["allowed_users"]

        # If the user is not already allowed, add their user ID to the
        # allowed_users list
        if not str(user.id) in allowed_users:
            allowed_users = f"{allowed_users}{user.id},"
            config.set("telegram_bot", "allowed_users", allowed_users)

            with open("config.ini", "w") as configfile:
                config.write(configfile)

        # Let the user know they have successfully authenticated
        await update.message.reply_text(
            "Success! ✅ You can now communicate with me! I have added a menu "
            "to your keyboard, which you can use to interact with me. If you "
            "don't see it, type /menu. If you need help just try /help",
            reply_markup=home_menu,
        )
        log_authenticated_access(
            update.effective_user.username, "/authenticate"
        )
    else:
        # Let the user know they have failed authentication
        await update.message.reply_text(
            "WRONG PASSWORD! 🛑 YOUR FAILED LOGIN ATTEMPT WILL BE LOGGED 📃 "
            "AND COMMUNICATED TO THE OTHER USERS!"
        )
        logger.critical(
            f"{user.username} tried to authenticate. The password was wrong."
        )

    return ConversationHandler.END


async def get_notification_settings(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if is_user_authenticated(update.effective_user.id):
        # Read the config file to get the current notification settings
        config.read("config.ini")
        user_id = update.effective_user.id

        # Determine whether the user is currently subscribed to loud and/or
        # silent notifications and store accordingly different option buttons
        current_setting_loud = (
            "➕ ACTIVATE"
            if str(user_id) not in config["telegram_bot"]["notifications_loud"]
            else "➖ DISABLE"
        )
        current_setting_silent = (
            "➕ ACTIVATE"
            if str(user_id)
            not in config["telegram_bot"]["notifications_silent"]
            else "➖ DISABLE"
        )

        # Display the current notification settings to the user and provide
        # options to change the settings
        await update.message.reply_text(
            "WHAT WOULD YOU LIKE TO CHANGE?",
            reply_markup=ReplyKeyboardMarkup.from_column(
                [
                    KeyboardButton(
                        text=f"{current_setting_loud} "
                        "AUTOMATIC MESSAGES (LOUD)"
                    ),
                    KeyboardButton(
                        text=f"{current_setting_silent} "
                        "AUTOMATIC MESSAGES (SILENT)"
                    ),
                ],
                resize_keyboard=False,
                one_time_keyboard=True,
                input_field_placeholder="Choose an option",
            ),
        )

        # Return the next step in the conversation
        return NOTIFICATION_SETTING


async def change_notifications_setting(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    try:
        # Read the configuration file to get the current notification settings
        config.read("config.ini")

        # Get the user's selection from the keyboard
        selection = update.message.text

        # Determine if the user wants to change loud or silent notifications
        setting = (
            "notifications_loud"
            if "LOUD" in selection
            else "notifications_silent"
        )

        # Get the current notification setting for the user
        current_setting = config["telegram_bot"][setting]

        # If the user wants to activate notifications, add their user ID to
        # the list
        if "ACTIVATE" in selection:
            current_setting = f"{current_setting}{update.effective_user.id},"
        # If the user wants to disable notifications, remove their user ID
        # from the list
        else:
            current_setting = current_setting.replace(
                f"{update.effective_user.id},", ""
            )

        # Update the configuration file with the new notification settings
        config.set("telegram_bot", setting, current_setting)

        # Save the updated configuration file
        with open("config.ini", "w") as configfile:
            config.write(configfile)

        # Notify the user that their setting has been changed
        await update.message.reply_text("✅ DONE", reply_markup=home_menu)
    except Exception as e:
        # If an error occurs, notify the user
        logger.critical(e)
        await update.message.reply_text(
            "I'm sorry but while I was processing your request an "
            "error occurred!",
            reply_markup=home_menu,
        )
    # End the conversation handler
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if is_user_authenticated(update.effective_user.id):
        await update.message.reply_text(
            "Conversation cancelled ❌",
            reply_markup=home_menu,
        )
        log_authenticated_access(update.effective_user.username, "/cancel")
        # End the conversation handler
        return ConversationHandler.END
    else:
        log_authenticated_access(update.effective_user.username, "/cancel")


async def recheck(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Check if the user is authenticated to use the bot
    if is_user_authenticated(update.effective_user.id):
        try:
            # Parse the data from the inline button callback query
            query = update.callback_query
            await query.answer()
            type, description, hostname, recheck_id = query.data.split(",")
            recheck_id = int(recheck_id) + 1

            # Call a function to get the status of the server or service
            message = (
                get_host_status(hostname)
                if description == "HOST STATUS"
                else get_service_details(hostname, description)
            )

            # Get the current date and time
            current_datetime = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

            # Edit the message with the latest status and a new inline button
            # for rechecking
            await query.edit_message_text(
                text=f"(🔂 RECHECK {recheck_id} - {current_datetime})\n\n"
                f"{message}",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "🔂 RECHECK",
                                callback_data=f"recheck,"
                                f"{description},"
                                f"{hostname},"
                                "0",
                            ),
                            InlineKeyboardButton(
                                "📉 GET SERVICE GRAPHS",
                                callback_data=f"graph,"
                                f"{description},"
                                f"{hostname}",
                            ),
                        ]
                    ]
                ),
                parse_mode="HTML",
            )
            log_authenticated_access(update.effective_user.username, "recheck")
        except Exception as e:
            # Handle errors by editing the message with an error message and
            # the home menu button
            logger.critical(e)
            await query.edit_message_text(
                "I'm sorry but while I was processing your request an "
                "error occurred!",
                reply_markup=home_menu,
            )
    else:
        log_unauthenticated_access(update.effective_user.username, "recheck")


async def post_print_service_graphs(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    # Check if the user is authenticated to use the bot
    if is_user_authenticated(update.effective_user.id):
        query = update.callback_query
        await query.answer()
        type, description, hostname = query.data.split(",")

        try:
            await context.bot.send_message(
                f"<u><b>📉 {description} GRAPH(s) FROM {hostname}</b></u>:\n"
                "This may take a second.",
                chat_id=update.effective_user.id,
                disable_notification=True,
                parse_mode="HTML",
            )
            graphs = get_service_graphs(hostname, description)

            for chunk in graphs:
                await context.bot.send_media_group(
                    media=chunk,
                    chat_id=update.effective_user.id,
                    disable_notification=True,
                )
        except Exception as e:
            # If an error occurs, notify the user
            logger.critical(e)
            await update.message.reply_text(
                "I'm sorry but while I was processing your request an "
                "error occurred!",
                reply_markup=home_menu,
            )


async def send_automatic_notification(context: ContextTypes.DEFAULT_TYPE):
    # Read the notification details from the file passed via the job scheduler
    notificaion_variables = open(context.job.data, "r").read().split(";")
    (
        type,
        ip,
        hostname,
        hostgroup,
        description,
        from_state,
        to_state,
        output,
    ) = notificaion_variables

    # Read the recipient list for the corresponding notification type from the
    # config file
    config.read("config.ini")
    recipient_list = config["telegram_bot"][type].split(",")

    # Get the state details in the form of emoji and text for both from_state
    # and to_state
    to_state_emoji = get_state_details(to_state)[0]
    to_state_txt = f"{to_state_emoji} {to_state}"

    from_state_emoji = get_state_details(from_state)[0]
    from_state_txt = f"{from_state_emoji} {from_state}"

    # Construct the message to be sent
    message = (
        f"{to_state_emoji} <u><b>{hostname}</b></u>\n\n"
        f"{description}\n"
        f"{from_state_txt} → {to_state_txt}"
        "\n\n<u><b>OUTPUT:</b></u>\n"
        f"<code><pre>{html.escape(output)}</pre></code>"
        "\n\n<u><b>DETAILS:</b></u>\n"
        f"IP: {ip}\n"
        f"HOSTGROUP: {hostgroup}\n"
    )

    # Send the message to all the recipients in the recipient list
    for recipient in recipient_list:
        if recipient.isnumeric():
            reply_markup = [
                InlineKeyboardButton(
                    "🔂 RECHECK",
                    callback_data=f"recheck,{description},{hostname},0",
                )
            ]

            if description != "":
                reply_markup.append(
                    InlineKeyboardButton(
                        "📉 GET SERVICE GRAPHS",
                        callback_data=f"graph,{description},{hostname}",
                    ),
                )

            await context.bot.send_message(
                chat_id=recipient,
                disable_notification=True
                if type == "notifications_silent"
                else False,
                text=message,
                reply_markup=InlineKeyboardMarkup([reply_markup]),
                parse_mode="HTML",
            )

    # Remove the file containing the notification details
    os.remove(context.job.data)


def main() -> None:
    # Add command handlers
    bot_handler.add_handler(CommandHandler("start", start))
    bot_handler.add_handler(CommandHandler("menu", start))
    bot_handler.add_handler(CommandHandler("help", help_command))
    bot_handler.add_handler(CommandHandler("cancel", cancel))

    # Add conversation handlers for various commands
    # "⭕ GET HOST STATUS" command
    bot_handler.add_handler(
        ConversationHandler(
            entry_points=[
                MessageHandler(
                    filters.Regex("^(⭕ GET HOST STATUS)$"), get_host_group
                )
            ],
            states={
                HOSTGROUP: [MessageHandler(filters.TEXT, get_host_name)],
                HOSTNAME: [MessageHandler(filters.TEXT, print_host_status)],
            },
            fallbacks=[],
        )
    )

    # "📃 GET SERVICES OF HOST" command
    bot_handler.add_handler(
        ConversationHandler(
            entry_points=[
                MessageHandler(
                    filters.Regex("^(📃 GET SERVICES OF HOST)$"), get_host_group
                )
            ],
            states={
                HOSTGROUP: [MessageHandler(filters.TEXT, get_host_name)],
                HOSTNAME: [MessageHandler(filters.TEXT, get_services)],
            },
            fallbacks=[],
        )
    )

    # "🔍 GET SERVICE DETAILS" command
    bot_handler.add_handler(
        ConversationHandler(
            entry_points=[
                MessageHandler(
                    filters.Regex("^(🔍 GET SERVICE DETAILS)$"), get_host_group
                )
            ],
            states={
                HOSTGROUP: [MessageHandler(filters.TEXT, get_host_name)],
                HOSTNAME: [MessageHandler(filters.TEXT, get_service_name)],
                SERVICE: [MessageHandler(filters.TEXT, print_service_details)],
            },
            fallbacks=[],
        )
    )

    # "❗❗ GET ALL HOST PROBLEMS" command
    bot_handler.add_handler(
        ConversationHandler(
            entry_points=[
                MessageHandler(
                    filters.Regex("^(🔥 GET ALL HOST PROBLEMS)$"),
                    get_host_group,
                )
            ],
            states={
                HOSTGROUP: [MessageHandler(filters.TEXT, get_host_problems)]
            },
            fallbacks=[],
        )
    )

    # "❗ GET ALL SERVICE PROBLEMS" command
    bot_handler.add_handler(
        ConversationHandler(
            entry_points=[
                MessageHandler(
                    filters.Regex("^(❗ GET ALL SERVICE PROBLEMS)$"),
                    get_host_group,
                )
            ],
            states={
                HOSTGROUP: [MessageHandler(filters.TEXT, get_service_problems)]
            },
            fallbacks=[],
        )
    )

    # "authenticate" command
    bot_handler.add_handler(
        ConversationHandler(
            entry_points=[CommandHandler("authenticate", get_pw)],
            states={PW: [MessageHandler(filters.TEXT, try_to_authenticate)]},
            fallbacks=[],
        )
    )

    # "🔔 NOTIFICATION SETTINGS" command
    bot_handler.add_handler(
        ConversationHandler(
            entry_points=[
                MessageHandler(
                    filters.Regex("^(🔔 NOTIFICATION SETTINGS)$"),
                    get_notification_settings,
                )
            ],
            states={
                NOTIFICATION_SETTING: [
                    MessageHandler(filters.TEXT, change_notifications_setting)
                ]
            },
            fallbacks=[],
        )
    )

    # "📉 GET SERVICE GRAPHS" command
    bot_handler.add_handler(
        ConversationHandler(
            entry_points=[
                MessageHandler(
                    filters.Regex("^(📉 GET SERVICE GRAPHS)$"), get_host_group
                )
            ],
            states={
                HOSTGROUP: [MessageHandler(filters.TEXT, get_host_name)],
                HOSTNAME: [MessageHandler(filters.TEXT, get_service_name)],
                SERVICE: [MessageHandler(filters.TEXT, print_service_graphs)],
            },
            fallbacks=[],
        )
    )

    # Add callback handler for "🔂 RECHECK" button
    bot_handler.add_handler(CallbackQueryHandler(recheck, pattern="^recheck,"))

    # Add callback handler for "📉 GET SERVICE GRAPHS" button
    bot_handler.add_handler(
        CallbackQueryHandler(post_print_service_graphs, pattern="^graph,")
    )

    # Start polling for updates
    bot_handler.run_polling()


if __name__ == "__main__":
    # Create File Watchdog called NotifyHandler
    event_handler = NotifyHandler()
    observer = Observer()

    # Schedule the observer to watch notify_query_path for new files
    observer.schedule(event_handler, path=notify_query_path, recursive=False)

    # Remove existing files in the directory
    for file in os.listdir(notify_query_path):
        file_path = os.path.join(notify_query_path, file)
        if os.path.isfile(file_path):
            os.remove(file_path)

    # Start the observer and the main bot function
    observer.start()
    main()
