<img src="src/checkmk-telegram-bot-banner.png" alt="Telegram Bot" height="auto" />
This Telegram bot provides an interface to your Check_MK server. It allows you to send automatic error messages (alerts) via Telegram and to manually read out information about hosts and services.

<hr>

- [Examples](#examples)
- [Info](#info)
- [System recommendations](#system-recommendations)
- [The Installation / Update process](#the-installation--update-process)
- [Uninstall the Bot](#uninstall-the-bot)
- [Usage](#usage)
    - [Authenticate](#authenticate)
    - [Receive information about hosts and services](#receive-information-about-hosts-and-services)
    - [Enable and disable notifications](#enable-and-disable-notifications)
- [Troubleshooting Guide](#troubleshooting-guide)
- [Support my work](#support-my-work)

<hr>

# Examples
<img src="src/Screenshot_01.png" width="23%"></img> <img src="src/Screenshot_02.jpg" width="23%"></img> <img src="src/Screenshot_03.png" width="23%"></img> <img src="src/Screenshot_07.png" width="23%"></img>

# Info
This bot is NOT meant to be used in groups.

# System recommendations
- CheckMK Version 2.1.p25 or higher
- The programs python3, pip3, git, runuser & sed installed on the server

# The Installation / Update process
1. Install the bot. <br>
Replace the variables in <> with your respective information.<br>
- omd_site_name (Your OMD Check_MK site which you want to monitor)
- api_token (You get this token from the BotFather of Telegram)
- bot_password (This can be a password of your choice, which will be used later to authenticate to the bot)
```bash
wget https://raw.githubusercontent.com/deexno/checkmk-telegram-plus/main/install.sh
bash install.sh <omd_site_name> <api_token> <bot_password>
```

2. Create a rule that exports the notifications using our new Notification Plugin.
<img src="src/Screenshot_04.png" alt="Telegram Bot" height="auto" width="700" />
For your information, you can use the first parameter to determine whether a notification should be sent loud (notifications_loud) or silent (notifications_silent). Silent notifications pop up in the chat, but the device does not vibrate or make a notification sound. This method can be used, for example, to differentiate between important and unimportant notifications.<br><br>

**To update the bot, simply download the install.sh file again as mentioned above and run it with the 3 required arguments**

# Uninstall the Bot
1. Stop the bot
```bash
omd_site_name=<omd_site_name>
systemctl stop checkmk-telegram-plus-$omd_site_name
rm /etc/systemd/system/checkmk-telegram-plus-$omd_site_name.service
systemctl daemon-reload
```

2. Delete all notification rules you have created regarding this bot (as described in step 2 of the installation).

3. Clean and remove all data concerning the bot
```bash
rm -Rf /omd/sites/$omd_site_name/local/share/check_mk/notifications/telegram_plus_notify_listener
rm -Rf /omd/sites/$omd_site_name/local/share/checkmk-telegram-plus
```

# Usage
### Authenticate
By default, the bot doesn't allow any communication until you authenticate with the previously set password in the configuration file. Here's an example:
<br><img src="src/Screenshot_05.png" alt="Telegram Bot" height="auto" width="600" />

### Receive information about hosts and services
Retrieving data manually is easy. After authentication, you should see a new icon next to the keyboard – the menu button. Open the menu and select an option. The bot will ask for necessary info and provide results (as seen in the examples).

### Enable and disable notifications
You can enable or disable messages through the bot. "Loud" and "silent" notifications can also be toggled independently. Note that this setting is ONLY FOR YOU, and all other users will still receive their notifications as normal. **And they are decativated by default! So don't forget to activate them!**
<br><img src="src/Screenshot_06.png" alt="Telegram Bot" height="auto" width="600" />

### Activate the admin settings ONLY for certain users
If you only want to activate the admin settings ONLY for certain users, follow these steps:
1. Open the config file of the bot
```
omd_site_name=<omd_site_name>
nano /omd/sites/$omd_site_name/local/share/checkmk-telegram-plus/config.ini
```
2. If the option ‘admin_users’ does not yet exist in the config file, create it under the [telegram_bot] tab:
```
[telegram_bot]
...
allowed_users = XXX
admin_users =
notifications_loud = XXX
...
```
3. Whitelist all users for whom you want to activate the admin option by listing their user ID under admin_users. You will find the ID of the respective users under allowed_users once they have verified themselves at the Telegram bot
```
# Example Config
[telegram_bot]
...
allowed_users = deexno (987654321),adminuser2 (123456789),ViewUser0 (000000000),
admin_users = deexno (987654321),adminuser2 (123456789),
notifications_loud = XXX
```
4. Restart the Bot
```
systemctl restart checkmk-telegram-plus-$omd_site_name.service
```

# Troubleshooting Guide
<b><a href="TROUBLESHOOTING.md">TROUBLESHOOTING GUIDE 🔨</a></b>

# Mentions and articles about the bot
[TUTONAUT](https://www.tutonaut.de/en/Receive-checkmk-notifications-via-telegram/)<br>
[DEVINSIDER](https://www.dev-insider.de/kundenservice-verbesserung-mit-chatbots-ki-a-2ccfbe16571dd9071bdb096199ea82b7/)

# Support my work
<a href="https://www.buymeacoffee.com/deexno" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/default-orange.png" alt="Buy Me A Coffee" height="41" width="174"></a>
<a href="https://www.paypal.com/paypalme/deexno" target="_blank"><img src="https://img.shields.io/badge/Support me-00457C?style=for-the-badge&logo=paypal&logoColor=white" height="41" /></a>
