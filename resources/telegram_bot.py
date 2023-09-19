import base64
import configparser
import html
import logging
import os
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

import fqueue
import livestatus
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
from translate import Translator

# Read configuration file
config = configparser.RawConfigParser()
config.read("config.ini")

# Get Open Monitoring Distribution (OMD) site
omd_site = config["check_mk"]["site"]
omd_site_dir = os.path.join("/", "omd", "sites", omd_site)

logger = logging.getLogger(__name__)
formatter = logging.Formatter(
    "%(asctime)s:%(levelname)s:%(funcName)s:%(message)s"
)

log_file_path = os.path.join(
    "/", "omd", "sites", omd_site, "var", "log", "telegram-plus.log"
)
log_file_handler = logging.FileHandler(log_file_path, mode="a")
log_file_handler.setLevel(logging.DEBUG)
log_file_handler.setFormatter(formatter)
logger.addHandler(log_file_handler)

# Get Telegram Bot API token from configuration file
telegram_bot_token = config["telegram_bot"]["api_token"]

# Define constants for conversation handler
HOSTGROUP, HOSTNAME, SERVICE, PW, NOTIFICATION_SETTING, OPTION = range(6)

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
        [
            KeyboardButton(text="📉 GET SERVICE GRAPHS"),
            KeyboardButton(text="🔄 RESCHEDULE CHECK"),
        ],
        [
            KeyboardButton(text="⚙️ ADMIN SETTINGS"),
        ],
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
notify_query_folder = os.path.join(omd_site_dir, "tmp", "telegram_plus")
notify_query_path = os.path.join(notify_query_folder, "notifications.queue")
# Create Query Path if it does not exist
Path(notify_query_folder).mkdir(parents=True, exist_ok=True)

notifcation_queue = fqueue.Queue(notify_query_path)
gpt = None


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

languages = [
    KeyboardButton(text="Deutsch: 🇩🇪 de"),
    KeyboardButton(text="Italiano: 🇮🇹 it"),
    KeyboardButton(text="English: 🇬🇧 en"),
    KeyboardButton(text="Русский: 🇷🇺 ru"),
    KeyboardButton(text="Español: 🇪🇸 es"),
    KeyboardButton(text="Français: 🇫🇷 fr"),
    KeyboardButton(text="中文: 🇨🇳 zh"),
    KeyboardButton(text="日本語: 🇯🇵 ja"),
    KeyboardButton(text="Português: 🇵🇹 pt"),
    KeyboardButton(text="العربية: 🇸🇦 ar"),
    KeyboardButton(text="Nederlands: 🇳🇱 nl"),
    KeyboardButton(text="Türkçe: 🇹🇷 tr"),
    KeyboardButton(text="Svenska: 🇸🇪 sv"),
    KeyboardButton(text="Polski: 🇵🇱 pl"),
    KeyboardButton(text="한국어: 🇰🇷 ko"),
    KeyboardButton(text="Dansk: 🇩🇰 da"),
    KeyboardButton(text="Suomi: 🇫🇮 fi"),
    KeyboardButton(text="Norsk: 🇳🇴 no"),
    KeyboardButton(text="Čeština: 🇨🇿 cs"),
    KeyboardButton(text="हिन्दी: 🇮🇳 hi"),
    KeyboardButton(text="Ελληνικά: 🇬🇷 el"),
    KeyboardButton(text="עברית: 🇮🇱 he"),
    KeyboardButton(text="Magyar: 🇭🇺 hu"),
    KeyboardButton(text="Indonesia: 🇮🇩 id"),
    KeyboardButton(text="Slovenský: 🇸🇰 sk"),
    KeyboardButton(text="ไทย: 🇹🇭 th"),
    KeyboardButton(text="Tiếng Việt: 🇻🇳 vi"),
    KeyboardButton(text="Română: 🇷🇴 ro"),
    KeyboardButton(text="Català: 🇪🇸 ca"),
    KeyboardButton(text="Hrvatski: 🇭🇷 hr"),
    KeyboardButton(text="Українська: 🇺🇦 uk"),
    KeyboardButton(text="Slovenščina: 🇸🇮 sl"),
    KeyboardButton(text="Bahasa Melayu: 🇲🇾 ms"),
    KeyboardButton(text="Български: 🇧🇬 bg"),
    KeyboardButton(text="Eesti: 🇪🇪 et"),
    KeyboardButton(text="Lietuvių: 🇱🇹 lt"),
    KeyboardButton(text="Latviešu: 🇱🇻 lv"),
    KeyboardButton(text="فارسی: 🇮🇷 fa"),
    KeyboardButton(text="Filipino: 🇵🇭 tl"),
    KeyboardButton(text="Srpksi: 🇷🇸 sr"),
    KeyboardButton(text="മലയാളം: 🇮🇳 ml"),
    KeyboardButton(text="ਪੰਜਾਬੀ: 🇮🇳 pa"),
    KeyboardButton(text="தமிழ்: 🇮🇳 ta"),
    KeyboardButton(text="বাংলা: 🇧🇩 bn"),
    KeyboardButton(text="తెలుగు: 🇮🇳 te"),
    KeyboardButton(text="ಕನ್ನಡ: 🇮🇳 kn"),
    KeyboardButton(text="ગુજરાતી: 🇮🇳 gu"),
    KeyboardButton(text="ଓଡ଼ିଆ: 🇮🇳 or"),
    KeyboardButton(text="සිංහල: 🇱🇰 si"),
    KeyboardButton(text="ဗမာ: 🇲🇲 my"),
    KeyboardButton(text="ភាសាខ្មែរ: 🇰🇭 km"),
]


def notifcation_listener():
    while True:
        try:
            for notification in notifcation_queue.get_queue():
                bot_handler_job_queue.run_once(
                    send_automatic_notification, 3, data=notification["event"]
                )
                notifcation_queue.drop_item(notification["id"])

            time.sleep(5)
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


# Method to get the state "details"
def update_config(section, key, value):
    config.set(section, key, value)

    with open("config.ini", "w") as configfile:
        config.write(configfile)


# Method to shorten the code and make translation easier
def translate(text):
    config.read("config.ini")

    # If the language is not present (e.g. due to an upgrade from an old
    # version to a new one), create it
    if not config.has_option("telegram_bot", "language"):
        update_config("telegram_bot", "language", "en")

    output_language = config["telegram_bot"]["language"]
    translator = Translator(to_lang=output_language)

    if not output_language == "en":
        return translator.translate(text)
    else:
        return text


def get_bot_version_details():
    details = requests.get(
        "https://api.github.com/repos/"
        "deexno/checkmk-telegram-plus/releases/latest"
    )

    if config.has_option("telegram_bot", "version"):
        installed_version = config["telegram_bot"]["version"]
        up_to_date = details.json()["tag_name"] == installed_version

        version_summary = (
            f"<u><b>{translate('BOT VERSION DETAILS')}:</b></u>\n"
            f"{translate('LATEST VERSION')}: "
            f"{details.json()['tag_name']}\n"
            f"{translate('INSTALLED VERSION')}: "
            f"{'Yes' if up_to_date else 'No'} ({installed_version})\n"
            f"{translate('PUPLISHED AT')}: "
            f"{details.json()['published_at']}\n\n"
            f"<u><b>{translate('CHANGES')}:</b></u>\n"
            f"{translate(details.json()['body'])}\n\n"
            "<a href='https://github.com/deexno/checkmk-telegram-plus'>"
            f"{translate('OPEN THE UPDATE/INSTALLATION GUIDE')}</a>\n\n"
            "<a href='https://www.paypal.com/paypalme/deexno'>"
            f"{translate('SUPPORT MY WORK')} ❤️</a>\n"
            "<a href='https://www.buymeacoffee.com/deexno'>"
            f"{translate('BUY ME A COFFE')} ☕</a>"
        )
    else:
        up_to_date = False
        version_summary = translate(
            "Your installed version could not be recognised 😓"
        )

    return up_to_date, version_summary


# Method to initially start the conversation with the bot
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Get the userdetails
    user = update.effective_user

    # Check if the user is authenticated
    if is_user_authenticated(user.id):
        # Send message to the user with the home menu
        await update.message.reply_text(
            translate(
                f"Hi! {user.username} 👋. I have added a menu to your "
                "keyboard ⌨️, which you can use to interact with me. If "
                "you don't see it, type /menu. If you need help just try /help"
            ),
            reply_markup=home_menu,
        )
        log_authenticated_access(user.username, update.message.text)
    else:
        # Send error message to the user if not authenticated
        await update.message.reply_text(
            translate(
                "You are not authenticated! 🔐 When using the bot for the "
                "first time, you must authenticate yourself with a password. "
                "If you do not do this, the bot 🤖 will not respond to any of "
                "your further requests."
            )
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
        await update.message.reply_html(
            translate(
                "<a href='https://github.com/deexno/checkmk-telegram-plus'>"
                "GET HELP"
                "</a>"
            )
        )
        log_authenticated_access(
            update.effective_user.username, update.message.text
        )
    else:
        log_unauthenticated_access(
            update.effective_user.username, update.message.text
        )


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
            translate("PLEASE TELL ME THE HOSTNAME"),
            reply_markup=ReplyKeyboardMarkup.from_column(
                hosts,
                resize_keyboard=False,
                one_time_keyboard=True,
                input_field_placeholder=translate("SELECT A HOST IN THE MENU"),
            ),
        )

    except Exception as e:
        logger.critical(e)
        await update.message.reply_text(
            translate(
                "I'm sorry but while I was processing your request an "
                "error occurred!"
            ),
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
                translate("PLEASE TELL ME THE HOSTGROUP OF THE HOST"),
                reply_markup=ReplyKeyboardMarkup.from_column(
                    hostgroups,
                    resize_keyboard=False,
                    one_time_keyboard=True,
                    input_field_placeholder=translate(
                        "SELECT A HOSTGROUP IN THE MENU"
                    ),
                ),
            )
            log_authenticated_access(
                update.effective_user.username, update.message.text
            )

        # Catch any exception that may occur
        except Exception as e:
            logger.critical(e)
            await update.message.reply_text(
                translate(
                    "I'm sorry but while I was processing your request an "
                    "error occurred!"
                )
            )

        return HOSTGROUP
    else:
        log_unauthenticated_access(
            update.effective_user.username, update.message.text
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
            translate("PLEASE TELL ME THE SERVICE NAME"),
            reply_markup=ReplyKeyboardMarkup.from_column(
                services,
                resize_keyboard=False,
                one_time_keyboard=True,
                input_field_placeholder=translate(
                    "SELECT A SERVICE IN THE MENU"
                ),
            ),
        )

    # Catch any errors
    except Exception as e:
        logger.critical(e)
        await update.message.reply_text(
            translate(
                "I'm sorry but while I was processing your request an "
                "error occurred!"
            ),
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
            translate(state),
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
            translate(
                "I'm sorry but while I was processing your request an "
                "error occurred!"
            ),
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
        f"<b>{translate('SUMMARY')}: </b>\n"
        f"<code><pre>{html.escape(service[0][3])}</pre></code>\n\n"
        f"<b>{translate('DETAILS')}: </b>\n"
        f"<code><pre>{html.escape(service[0][4])}</pre></code>\n\n"
        f"<b>{translate('METRICS')}: </b>\n"
    )

    # Add any available metrics to the details string
    if len(service[0][2]) > 1:
        for metric in service[0][2].split(" "):
            if "=" in metric:
                name, values = metric.split("=")
                value, warn, crit, min, max = values.split(";")
                details += f"{name}: {value}\n"
    else:
        details += translate("No metrics available\n")

    # Add last check time to the details string
    details += (
        f"\n<b>{translate('INFO')}: </b>\n"
        f"{translate('Last Check')}: {datetime.fromtimestamp(service[0][5])}"
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
            translate(
                "I'm sorry but while I was processing your request an "
                "error occurred!"
            ),
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
            translate(
                f"<u><b>📉 {service} GRAPHS FROM {hostname}</b></u>:\n"
                "This may take a second."
            ),
            reply_markup=home_menu,
        )

        # Get the graphs for the specified service on the specified host
        graphs = get_service_graphs(hostname, service)

        # Reply to the user with the graphs, chunked into groups of 10
        if len(graphs) > 0:
            for chunk in graphs:
                await update.message.reply_media_group(media=chunk)
        else:
            await update.message.reply_text(
                translate("No graphs are available"),
                reply_markup=home_menu,
            )

    except Exception as e:
        # If an error occurs, print the error and reply with an error message
        logger.critical(e)
        await update.message.reply_text(
            translate(
                "I'm sorry but while I was processing your request an "
                "error occurred!"
            ),
            reply_markup=home_menu,
        )

    # End the conversation handler
    return ConversationHandler.END


async def reschedule_check(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    # Extract hostname from user's message
    hostname = update.message.text

    try:
        # Reply to the user that we are processing their request
        await update.message.reply_html(
            translate("The check will be started. Please wait. ⏳"),
            reply_markup=home_menu,
        )

        # Execute the check via the CMK CLI and save the output in a variable
        # to output it to the user afterwards.
        check_result = subprocess.run(
            [os.path.join(omd_site_dir, "bin", "cmk"), "--check", hostname],
            stdout=subprocess.PIPE,
        )

        # Return the answer of the check to the user
        await update.message.reply_html(
            f"{check_result.stdout.decode('utf-8')}\n\n"
            f"{translate('RESCHEDULE CHECK WAS COMPLETED SUCCESSFULLY')}",
            reply_markup=home_menu,
        )

    except Exception as e:
        # If an error occurs, print the error and reply with an error message
        logger.critical(e)
        await update.message.reply_text(
            translate(
                "I'm sorry but while I was processing your request an "
                "error occurred!"
            ),
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
            f"<u><b>{translate('HOST PROBLEMS')} "
            f"({len(host_problems_array)}):</b></u>\n\n"
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
            translate(
                "I'm sorry but while I was processing your request an "
                "error occurred!"
            ),
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
            f"<u><b>{translate('SERVICE PROBLEMS')} "
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
            translate(
                "I'm sorry but while I was processing your request an "
                "error occurred!"
            ),
            reply_markup=home_menu,
        )

    # End the conversation
    return ConversationHandler.END


async def get_pw_for_auth(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    # Check if the user is not already authenticated
    if not is_user_authenticated(update.effective_user.id):
        # If the user is not authenticated ask for the password
        await update.message.reply_text(translate("What is the password?"))
        return PW
    else:
        # If user is already authenticated, end the conversation
        await update.message.reply_text(
            translate(
                "You are already authenticated. "
                "✅ The process has been cancelled."
            )
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
        if str(user.id) not in allowed_users:
            allowed_users = (
                f"{allowed_users}{update.effective_user.username} ({user.id}),"
            )
            update_config("telegram_bot", "allowed_users", allowed_users)

        # Let the user know they have successfully authenticated
        await update.message.reply_text(
            translate(
                "Success! ✅ You can now communicate with me! I have added a "
                "menu to your keyboard, which you can use to interact with "
                "me. If you don't see it, type /menu. If you need help just "
                "try /help"
            ),
            reply_markup=home_menu,
        )
        log_authenticated_access(
            update.effective_user.username, "/authenticate"
        )
    else:
        # Let the user know they have failed authentication
        await update.message.reply_text(
            translate(
                "WRONG PASSWORD! 🛑 YOUR FAILED LOGIN ATTEMPT WILL "
                "BE LOGGED 📃 AND COMMUNICATED TO THE OTHER USERS!"
            )
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
            translate("WHAT WOULD YOU LIKE TO CHANGE?"),
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
                input_field_placeholder=translate("Choose an option"),
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

        update_config("telegram_bot", setting, current_setting)

        # Notify the user that their setting has been changed
        await update.message.reply_text(
            translate("✅ DONE"), reply_markup=home_menu
        )
    except Exception as e:
        # If an error occurs, notify the user
        logger.critical(e)
        await update.message.reply_text(
            translate(
                "I'm sorry but while I was processing your request an "
                "error occurred!"
            ),
            reply_markup=home_menu,
        )
    # End the conversation handler
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if is_user_authenticated(update.effective_user.id):
        await update.message.reply_text(
            translate("Conversation cancelled ❌"),
            reply_markup=home_menu,
        )
        log_authenticated_access(
            update.effective_user.username, update.message.text
        )
        # End the conversation handler
        return ConversationHandler.END
    else:
        log_authenticated_access(
            update.effective_user.username, update.message.text
        )


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
                text=translate(
                    f"(🔂 RECHECK {recheck_id} - {current_datetime})\n\n"
                    f"{message}"
                ),
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
                                "📉 GRAPHS",
                                callback_data=f"graph,"
                                f"{description},"
                                f"{hostname}",
                            ),
                        ]
                    ]
                ),
                parse_mode="HTML",
            )
            log_authenticated_access(
                update.effective_user.username, update.message.text
            )
        except Exception as e:
            # Handle errors by editing the message with an error message and
            # the home menu button
            logger.critical(e)
            await query.edit_message_text(
                translate(
                    "I'm sorry but while I was processing your request an "
                    "error occurred!"
                ),
                reply_markup=home_menu,
            )
    else:
        log_unauthenticated_access(
            update.effective_user.username, update.message.text
        )


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
                text=translate(
                    f"<u><b>📉 {description} GRAPH(s) FROM "
                    f"{hostname}</b></u>:\n"
                    "This may take a second."
                ),
                chat_id=update.effective_user.id,
                disable_notification=True,
                parse_mode="HTML",
            )

            graphs = get_service_graphs(hostname, description)

            if len(graphs) > 0:
                for chunk in graphs:
                    await context.bot.send_media_group(
                        media=chunk,
                        chat_id=update.effective_user.id,
                        disable_notification=True,
                    )
            else:
                await context.bot.send_message(
                    text=translate("No graphs are available"),
                    chat_id=update.effective_user.id,
                    reply_markup=home_menu,
                )
        except Exception as e:
            # If an error occurs, notify the user
            logger.critical(e)
            await context.bot.send_message(
                text=translate(
                    "I'm sorry but while I was processing your request an "
                    "error occurred!"
                ),
                chat_id=update.effective_user.id,
                reply_markup=home_menu,
            )


async def send_automatic_notification(context: ContextTypes.DEFAULT_TYPE):
    # Read the notification details from the file passed via the job scheduler
    notificaion_variables = context.job.data.split(";")
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
        f"\n\n<u><b>{translate('OUTPUT')}:</b></u>\n"
        f"<code><pre>{html.escape(output)}</pre></code>"
        f"\n\n<u><b>{translate('DETAILS')}:</b></u>\n"
        f"IP: {ip}\n"
        f"{translate('HOSTGROUP')}: {hostgroup}\n"
    )

    # Send the message to all the recipients in the recipient list
    for recipient in recipient_list:
        if recipient.isnumeric():
            reply_markup = [
                [
                    InlineKeyboardButton(
                        "🔂 RECHECK",
                        callback_data=f"recheck,{description},{hostname},0",
                    )
                ]
            ]

            if description != "":
                reply_markup = [
                    [
                        InlineKeyboardButton(
                            "🔂 RECHECK",
                            callback_data=f"recheck,{description},{hostname},0",
                        ),
                        InlineKeyboardButton(
                            "📉 GRAPHS",
                            callback_data=f"graph,{description},{hostname}",
                        ),
                    ],
                    [
                        InlineKeyboardButton(
                            "✔️ ACKNOWLEDGE",
                            callback_data=f"ack,{description},{hostname}",
                        )
                    ],
                ]

            await context.bot.send_message(
                chat_id=recipient,
                disable_notification=True
                if type == "notifications_silent"
                else False,
                text=message,
                reply_markup=InlineKeyboardMarkup(reply_markup),
                parse_mode="HTML",
            )


async def open_admin_settings(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    try:
        if is_user_authenticated(update.effective_user.id):
            # Read the configuration file to get the current
            # notification settings
            config.read("config.ini")

            # Notify the user that their setting has been changed
            await update.message.reply_text(
                translate("ADMINISTATOR SETTINGS WERE OPENED"),
                reply_markup=ReplyKeyboardMarkup(
                    [
                        [
                            KeyboardButton(text="📖 GET LOGS"),
                            KeyboardButton(text="🇩🇪 CHANGE LANGUAGE"),
                        ],
                        [
                            KeyboardButton(text="🔓 GET PASSWORD"),
                            KeyboardButton(text="🔒 CHANGE PASSWORD"),
                        ],
                        [
                            KeyboardButton(text="👥 LIST USERS"),
                            KeyboardButton(text="🗑️ DELETE USERS"),
                        ],
                        [
                            KeyboardButton(text="⬆️ CHECK FOR UPDATES"),
                            KeyboardButton(text="🔔 LIST NOTIFY QUEUE"),
                        ],
                        [
                            KeyboardButton(text="✴ GET OMD STATUS"),
                            KeyboardButton(text="⬆ START OMD SERVICES"),
                        ],
                        [
                            KeyboardButton(text="⬇ STOP OMD SERVICES"),
                        ],
                    ],
                    resize_keyboard=False,
                    one_time_keyboard=True,
                    input_field_placeholder="Choose an option",
                ),
            )
        else:
            log_unauthenticated_access(
                update.effective_user.username, update.message.text
            )
    except Exception as e:
        # If an error occurs, notify the user
        logger.critical(e)
        await update.message.reply_text(
            translate(
                "I'm sorry but while I was processing your request an "
                "error occurred!"
            ),
            reply_markup=home_menu,
        )
    # End the conversation handler
    return ConversationHandler.END


async def get_logs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        if is_user_authenticated(update.effective_user.id):
            log_path = os.path.join(omd_site_dir, "var", "log")
            log_file_path = os.path.join(log_path, "telegram-plus.log")

            log_file = open(log_file_path)
            logs = html.escape(log_file.read())
            log_file.close()

            events = translate(
                "<u><b>HERE ARE THE LAST 25 LOG ENTRIES:</b></u>:\n\n"
            )

            for event in logs.split("\n")[25:]:
                event = event.replace("CRITICAL:", translate("🛑 CRITICAL\n"))
                event = event.replace("WARNING:", translate("⚠ WARNING\n"))

                events += f"<code>{translate(event)}</code>\n\n"

            await update.message.reply_html(
                events,
                reply_markup=home_menu,
            )
            log_authenticated_access(
                update.effective_user.username, update.message.text
            )
        else:
            log_unauthenticated_access(
                update.effective_user.username, update.message.text
            )

    except Exception as e:
        logger.critical(e)
        await update.message.reply_text(
            translate(
                "I'm sorry but while I was processing your request an "
                "error occurred!"
            ),
            reply_markup=home_menu,
        )

    return ConversationHandler.END


async def display_password(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    try:
        if is_user_authenticated(update.effective_user.id):
            await update.message.reply_text(
                config["telegram_bot"]["password_for_authentication"],
                reply_markup=home_menu,
            )
            log_authenticated_access(
                update.effective_user.username, update.message.text
            )
        else:
            log_unauthenticated_access(
                update.effective_user.username, update.message.text
            )

    except Exception as e:
        logger.critical(e)
        await update.message.reply_text(
            translate(
                "I'm sorry but while I was processing your request an "
                "error occurred!"
            ),
            reply_markup=home_menu,
        )

    return ConversationHandler.END


async def get_pw(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if is_user_authenticated(update.effective_user.id):
        await update.message.reply_text(translate("What is the password?"))
        log_authenticated_access(
            update.effective_user.username, update.message.text
        )

        return PW
    else:
        log_unauthenticated_access(
            update.effective_user.username, update.message.text
        )
        return ConversationHandler.END


async def change_password(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    try:
        update_config(
            "telegram_bot", "password_for_authentication", update.message.text
        )

        await update.message.reply_text(
            translate("✅ DONE"),
            reply_markup=home_menu,
        )
    except Exception as e:
        logger.critical(e)
        await update.message.reply_text(
            translate(
                "I'm sorry but while I was processing your request an "
                "error occurred!"
            ),
            reply_markup=home_menu,
        )

    return ConversationHandler.END


async def list_users(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    try:
        if is_user_authenticated(update.effective_user.id):
            allowed_users = config["telegram_bot"]["allowed_users"]
            users_notify_l = config["telegram_bot"]["notifications_loud"]
            users_notify_s = config["telegram_bot"]["notifications_silent"]

            await update.message.reply_html(
                f"<u><b>{translate('ALLOWED USERS')}</b></u>:\n"
                f"{allowed_users}"
                f"\n\n<u><b>{translate('USERS WITH ACTIVE NOTIFICATIONS')} "
                "(LOUD)</b></u>:\n"
                f"{users_notify_l}"
                f"\n\n<u><b>{translate('USERS WITH ACTIVE NOTIFICATIONS')} "
                "(SILENT)</b></u>:\n"
                f"{users_notify_s}",
                reply_markup=home_menu,
            )

            log_authenticated_access(
                update.effective_user.username, update.message.text
            )
        else:
            log_unauthenticated_access(
                update.effective_user.username, update.message.text
            )

    except Exception as e:
        logger.critical(e)
        await update.message.reply_text(
            translate(
                "I'm sorry but while I was processing your request an "
                "error occurred!"
            ),
            reply_markup=home_menu,
        )

    return ConversationHandler.END


async def get_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        if is_user_authenticated(update.effective_user.id):
            users = []

            for user in config["telegram_bot"]["allowed_users"].split(","):
                if not user == "":
                    users.append(KeyboardButton(text=str(user)))

            await update.message.reply_text(
                translate("Select a user!"),
                reply_markup=ReplyKeyboardMarkup.from_column(
                    users,
                    resize_keyboard=False,
                    one_time_keyboard=True,
                    input_field_placeholder=translate(
                        "SELECT A USER IN THE MENU"
                    ),
                ),
            )
            log_authenticated_access(
                update.effective_user.username, update.message.text
            )

            return OPTION
        else:
            log_unauthenticated_access(
                update.effective_user.username, update.message.text
            )

    except Exception as e:
        logger.critical(e)
        await update.message.reply_text(
            translate(
                "I'm sorry but while I was processing your request an "
                "error occurred!"
            ),
            reply_markup=home_menu,
        )

    return ConversationHandler.END


async def delete_user(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    try:
        allowed_users = config["telegram_bot"]["allowed_users"]
        allowed_users = allowed_users.replace(f"{update.message.text},", "")
        update_config("telegram_bot", "allowed_users", allowed_users)

        await update.message.reply_text(
            translate("✅ DONE"),
            reply_markup=home_menu,
        )
    except Exception as e:
        logger.critical(e)
        await update.message.reply_text(
            translate(
                "I'm sorry but while I was processing your request an "
                "error occurred!"
            ),
            reply_markup=home_menu,
        )

    return ConversationHandler.END


async def list_notify_queue(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    try:
        if is_user_authenticated(update.effective_user.id):
            notifications = notifcation_queue.get_queue()
            notifications_count = len(notifications)

            await update.message.reply_text(
                translate(
                    "🚫 EMPTY"
                    if notifications_count == 0
                    else f"({notifications_count})\n\n{notifications}"
                ),
                reply_markup=home_menu,
            )

            log_authenticated_access(
                update.effective_user.username, update.message.text
            )

        else:
            log_unauthenticated_access(
                update.effective_user.username, update.message.text
            )

    except Exception as e:
        logger.critical(e)
        await update.message.reply_text(
            translate(
                "I'm sorry but while I was processing your request an "
                "error occurred!"
            ),
            reply_markup=home_menu,
        )

    return ConversationHandler.END


async def check_for_updates(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    try:
        if is_user_authenticated(update.effective_user.id):
            up_to_date, version_summary = get_bot_version_details()

            await update.message.reply_html(
                version_summary,
                reply_markup=home_menu,
            )

    except Exception as e:
        logger.critical(e)
        await update.message.reply_text(
            translate(
                "I'm sorry but while I was processing your request an "
                "error occurred!"
            ),
            reply_markup=home_menu,
        )

    return ConversationHandler.END


async def get_omd_status(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    try:
        # Execute the check via the OMD CLI
        check_result = subprocess.run(
            [os.path.join(omd_site_dir, "bin", "omd"), "status"],
            stdout=subprocess.PIPE,
        )

        # Return the answer of the check to the user
        await update.message.reply_html(
            f"<pre>{check_result.stdout.decode('utf-8')}</pre>",
            reply_markup=home_menu,
        )

    except Exception as e:
        # If an error occurs, print the error and reply with an error message
        logger.critical(e)
        await update.message.reply_text(
            translate(
                "I'm sorry but while I was processing your request an "
                "error occurred!"
            ),
            reply_markup=home_menu,
        )

    # End the conversation handler
    return ConversationHandler.END


async def start_omd_services(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    try:
        await update.message.reply_html(
            translate(
                "<u><b>THE SERVICES ARE ATTEMPTED TO START. "
                "PLEASE WAIT</b></u>"
            ),
            reply_markup=home_menu,
        )

        # Execute the start command via the OMD CLI
        check_result = subprocess.run(
            [os.path.join(omd_site_dir, "bin", "omd"), "start"],
            stdout=subprocess.PIPE,
        )

        # Return the answer of the check to the user
        await update.message.reply_html(
            f"<pre>{check_result.stdout.decode('utf-8')}</pre>",
            reply_markup=home_menu,
        )

    except Exception as e:
        # If an error occurs, print the error and reply with an error message
        logger.critical(e)
        await update.message.reply_text(
            translate(
                "I'm sorry but while I was processing your request an "
                "error occurred!"
            ),
            reply_markup=home_menu,
        )

    # End the conversation handler
    return ConversationHandler.END

async def stop_omd_services(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    try:
        await update.message.reply_html(
            translate(
                "<u><b>THE SERVICES ARE ATTEMPTED TO STOP. "
                "PLEASE WAIT</b></u>"
            ),
            reply_markup=home_menu,
        )

        # Execute the stop command via the OMD CLI
        check_result = subprocess.run(
            [os.path.join(omd_site_dir, "bin", "omd"), "stop"],
            stdout=subprocess.PIPE,
        )

        # Return the answer of the check to the user
        await update.message.reply_html(
            f"<pre>{check_result.stdout.decode('utf-8')}</pre>",
            reply_markup=home_menu,
        )

    except Exception as e:
        # If an error occurs, print the error and reply with an error message
        logger.critical(e)
        await update.message.reply_text(
            translate(
                "I'm sorry but while I was processing your request an "
                "error occurred!"
            ),
            reply_markup=home_menu,
        )

    # End the conversation handler
    return ConversationHandler.END

async def get_language(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    try:
        if is_user_authenticated(update.effective_user.id):
            await update.message.reply_text(
                translate(
                    "Select a language! Attention! If you choose a "
                    "language other than English, this may result in slower "
                    "response times! A correct translation is also not "
                    "guaranteed. The translation is based on google "
                    "Translate. Only static outputs are translated here. "
                    "Outputs of Check_MK itself remain in the original "
                    "format in order not to publish any misleading "
                    "information!"
                ),
                reply_markup=ReplyKeyboardMarkup.from_column(
                    languages,
                    resize_keyboard=False,
                    one_time_keyboard=True,
                    input_field_placeholder=translate(
                        "SELECT A LANGUAGE IN THE MENU"
                    ),
                ),
            )
            log_authenticated_access(
                update.effective_user.username, update.message.text
            )

            return OPTION
        else:
            log_unauthenticated_access(
                update.effective_user.username, update.message.text
            )

    except Exception as e:
        logger.critical(e)
        await update.message.reply_text(
            translate(
                "I'm sorry but while I was processing your request an "
                "error occurred!"
            ),
            reply_markup=home_menu,
        )

    return ConversationHandler.END


async def update_language(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    try:
        language_selected = update.message.text.split(" ")[2]
        update_config("telegram_bot", "language", language_selected)

        await update.message.reply_text(
            translate("✅ DONE"),
            reply_markup=home_menu,
        )
    except Exception as e:
        logger.critical(e)
        await update.message.reply_text(
            translate(
                "I'm sorry but while I was processing your request an "
                "error occurred!"
            ),
            reply_markup=home_menu,
        )

    return ConversationHandler.END


async def message_all_users(context: ContextTypes.DEFAULT_TYPE):
    # Read the recipient list for the corresponding notification type from the
    # config file
    config.read("config.ini")
    recipient_list = []

    for recipient in config["telegram_bot"]["allowed_users"].split(","):
        if recipient.isnumeric():
            # For older versions simply add the userid
            recipient_list.append(recipient)
        else:
            # For newer versions, extract the user ID from the user information
            recipient = recipient.split("(")[
                len(recipient.split("(")) - 1
            ].split(")")[0]

            if recipient != "":
                recipient_list.append(recipient)

    # Send the message to all the recipients in the recipient list
    for recipient in recipient_list:
        if recipient.isnumeric():
            await context.bot.send_message(
                chat_id=recipient,
                disable_notification=False,
                text=context.job.data,
                reply_markup=home_menu,
                parse_mode="HTML",
            )


async def acknowledge_service_problem(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    # Check if the user is authenticated to use the bot
    if is_user_authenticated(update.effective_user.id):
        query = update.callback_query
        await query.answer()
        type, description, hostname = query.data.split(",")

        now = int(time.time())
        nagios_cmd = os.path.join(omd_site_dir, "tmp", "run", "nagios.cmd")
        user = update.effective_user
        username = user.username

        comment = (
            "ACKNOWLEDGE_SVC_PROBLEM;"
            f"{hostname};"
            f"{description};"
            "2;"
            "0;"
            "0;"
            f"{username};"
            "The problem was acknowledged via the Telegram bot by "
            f"{username} ({user.id})."
        )

        with open(nagios_cmd, "w") as f:
            f.write(f"[{now}] {comment}\n")

        try:
            await context.bot.send_message(
                text=translate(
                    "The service was acknowledged:\n\n"
                    f"HOST: {hostname}\n"
                    f"SERVICE: {description}\n"
                    "STICKY: YES\n"
                    "NOTIFY OTHERS: YES\n"
                    "PERSISTEN: NO\n"
                ),
                chat_id=update.effective_user.id,
                disable_notification=True,
                parse_mode="HTML",
            )

            bot_handler_job_queue.run_once(
                message_all_users,
                0,
                data=translate(
                    f"@{username} has acknowledged ✅ the service "
                    f"'{description}' for the host '{hostname}'"
                ),
            )

        except Exception as e:
            # If an error occurs, notify the user
            logger.critical(e)
            await context.bot.send_message(
                text=translate(
                    "I'm sorry but while I was processing your request an "
                    "error occurred!"
                ),
                chat_id=update.effective_user.id,
                reply_markup=home_menu,
            )


def main() -> None:
    bot_handler_job_queue.run_once(
        message_all_users, 0, data=translate("I'm BACK! 🤖")
    )

    version_up_to_date, version_summary = get_bot_version_details()

    if not version_up_to_date:
        bot_handler_job_queue.run_once(
            message_all_users,
            0,
            data=f"Your Bot Version is not up-to-date! \n\n{version_summary}",
        )

    # Add command handlers
    bot_handler.add_handler(CommandHandler("start", start))
    bot_handler.add_handler(CommandHandler("menu", start))
    bot_handler.add_handler(CommandHandler("help", help_command))

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
                HOSTGROUP: [
                    MessageHandler(
                        filters.TEXT & (~filters.COMMAND), get_host_name
                    )
                ],
                HOSTNAME: [
                    MessageHandler(
                        filters.TEXT & (~filters.COMMAND), print_host_status
                    )
                ],
            },
            fallbacks=[CommandHandler("cancel", cancel)],
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
                HOSTGROUP: [
                    MessageHandler(
                        filters.TEXT & (~filters.COMMAND), get_host_name
                    )
                ],
                HOSTNAME: [
                    MessageHandler(
                        filters.TEXT & (~filters.COMMAND), get_services
                    )
                ],
            },
            fallbacks=[CommandHandler("cancel", cancel)],
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
                HOSTGROUP: [
                    MessageHandler(
                        filters.TEXT & (~filters.COMMAND), get_host_name
                    )
                ],
                HOSTNAME: [
                    MessageHandler(
                        filters.TEXT & (~filters.COMMAND), get_service_name
                    )
                ],
                SERVICE: [
                    MessageHandler(
                        filters.TEXT & (~filters.COMMAND),
                        print_service_details,
                    )
                ],
            },
            fallbacks=[CommandHandler("cancel", cancel)],
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
                HOSTGROUP: [
                    MessageHandler(
                        filters.TEXT & (~filters.COMMAND), get_host_problems
                    )
                ]
            },
            fallbacks=[CommandHandler("cancel", cancel)],
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
                HOSTGROUP: [
                    MessageHandler(
                        filters.TEXT & (~filters.COMMAND), get_service_problems
                    )
                ]
            },
            fallbacks=[CommandHandler("cancel", cancel)],
        )
    )

    # "authenticate" command
    bot_handler.add_handler(
        ConversationHandler(
            entry_points=[CommandHandler("authenticate", get_pw_for_auth)],
            states={
                PW: [
                    MessageHandler(
                        filters.TEXT & (~filters.COMMAND), try_to_authenticate
                    )
                ]
            },
            fallbacks=[CommandHandler("cancel", cancel)],
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
                    MessageHandler(
                        filters.TEXT & (~filters.COMMAND),
                        change_notifications_setting,
                    )
                ]
            },
            fallbacks=[CommandHandler("cancel", cancel)],
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
                HOSTGROUP: [
                    MessageHandler(
                        filters.TEXT & (~filters.COMMAND), get_host_name
                    )
                ],
                HOSTNAME: [
                    MessageHandler(
                        filters.TEXT & (~filters.COMMAND), get_service_name
                    )
                ],
                SERVICE: [
                    MessageHandler(
                        filters.TEXT & (~filters.COMMAND), print_service_graphs
                    )
                ],
            },
            fallbacks=[CommandHandler("cancel", cancel)],
        )
    )

    # "🔄 RESCHEDULE CHECK" command
    bot_handler.add_handler(
        ConversationHandler(
            entry_points=[
                MessageHandler(
                    filters.Regex("^(🔄 RESCHEDULE CHECK)$"), get_host_group
                )
            ],
            states={
                HOSTGROUP: [
                    MessageHandler(
                        filters.TEXT & (~filters.COMMAND), get_host_name
                    )
                ],
                HOSTNAME: [
                    MessageHandler(
                        filters.TEXT & (~filters.COMMAND), reschedule_check
                    )
                ],
            },
            fallbacks=[CommandHandler("cancel", cancel)],
        )
    )

    # "⚙️ ADMIN SETTINGS" command
    bot_handler.add_handler(
        ConversationHandler(
            entry_points=[
                MessageHandler(
                    filters.Regex("^(⚙️ ADMIN SETTINGS)$"), open_admin_settings
                )
            ],
            states={},
            fallbacks=[CommandHandler("cancel", cancel)],
        )
    )

    # "📖 GET LOGS" command
    bot_handler.add_handler(
        ConversationHandler(
            entry_points=[
                MessageHandler(filters.Regex("^(📖 GET LOGS)$"), get_logs)
            ],
            states={},
            fallbacks=[CommandHandler("cancel", cancel)],
        )
    )

    # "🔓 GET PASSWORD" command
    bot_handler.add_handler(
        ConversationHandler(
            entry_points=[
                MessageHandler(
                    filters.Regex("^(🔓 GET PASSWORD)$"), display_password
                )
            ],
            states={},
            fallbacks=[CommandHandler("cancel", cancel)],
        )
    )

    # "🔒 CHANGE PASSWORD" command
    bot_handler.add_handler(
        ConversationHandler(
            entry_points=[
                MessageHandler(filters.Regex("^(🔒 CHANGE PASSWORD)$"), get_pw)
            ],
            states={
                PW: [
                    MessageHandler(
                        filters.TEXT & (~filters.COMMAND), change_password
                    )
                ]
            },
            fallbacks=[CommandHandler("cancel", cancel)],
        )
    )

    # "👥 LIST USERS" command
    bot_handler.add_handler(
        ConversationHandler(
            entry_points=[
                MessageHandler(filters.Regex("^(👥 LIST USERS)$"), list_users)
            ],
            states={},
            fallbacks=[CommandHandler("cancel", cancel)],
        )
    )

    # "🗑️ DELETE USERS" command
    bot_handler.add_handler(
        ConversationHandler(
            entry_points=[
                MessageHandler(filters.Regex("^(🗑️ DELETE USERS)$"), get_user)
            ],
            states={
                OPTION: [
                    MessageHandler(
                        filters.TEXT & (~filters.COMMAND), delete_user
                    )
                ]
            },
            fallbacks=[CommandHandler("cancel", cancel)],
        )
    )

    # "⬆️ CHECK FOR UPDATES" command
    bot_handler.add_handler(
        ConversationHandler(
            entry_points=[
                MessageHandler(
                    filters.Regex("^(⬆️ CHECK FOR UPDATES)$"),
                    check_for_updates,
                )
            ],
            states={},
            fallbacks=[CommandHandler("cancel", cancel)],
        )
    )

    # "🔔 LIST NOTIFY QUEUE" command
    bot_handler.add_handler(
        ConversationHandler(
            entry_points=[
                MessageHandler(
                    filters.Regex("^(🔔 LIST NOTIFY QUEUE)$"), list_notify_queue
                )
            ],
            states={},
            fallbacks=[CommandHandler("cancel", cancel)],
        )
    )

    # "✴ GET OMD STATUS" command
    bot_handler.add_handler(
        ConversationHandler(
            entry_points=[
                MessageHandler(
                    filters.Regex("^(✴ GET OMD STATUS)$"), get_omd_status
                )
            ],
            states={},
            fallbacks=[CommandHandler("cancel", cancel)],
        )
    )

    # ⬆ START OMD SERVICES
    bot_handler.add_handler(
        ConversationHandler(
            entry_points=[
                MessageHandler(
                    filters.Regex("^(⬆ START OMD SERVICES)$"),
                    start_omd_services,
                )
            ],
            states={},
            fallbacks=[CommandHandler("cancel", cancel)],
        )
    )

    # STOP OMD SERVICES
    bot_handler.add_handler(
        ConversationHandler(
            entry_points=[
                MessageHandler(
                    filters.Regex("^(⬇ STOP OMD SERVICES)$"),
                    stop_omd_services,
                )
            ],
            states={},
            fallbacks=[CommandHandler("cancel", cancel)],
        )
    )

    # 🇩🇪 CHANGE LANGUAGE
    bot_handler.add_handler(
        ConversationHandler(
            entry_points=[
                MessageHandler(
                    filters.Regex("^(🇩🇪 CHANGE LANGUAGE)$"), get_language
                )
            ],
            states={
                OPTION: [
                    MessageHandler(
                        filters.TEXT & (~filters.COMMAND), update_language
                    )
                ]
            },
            fallbacks=[CommandHandler("cancel", cancel)],
        )
    )

    # Add callback handler for "🔂 RECHECK" button
    bot_handler.add_handler(CallbackQueryHandler(recheck, pattern="^recheck,"))

    # Add callback handler for "📉 GET SERVICE GRAPHS" button
    bot_handler.add_handler(
        CallbackQueryHandler(post_print_service_graphs, pattern="^graph,")
    )

    # Add callback handler for "✔️ ACKNOWLEDGE" button
    bot_handler.add_handler(
        CallbackQueryHandler(acknowledge_service_problem, pattern="^ack,")
    )

    # Start polling for updates
    bot_handler.run_polling()


if __name__ == "__main__":
    threading.Thread(target=notifcation_listener).start()
    main()
