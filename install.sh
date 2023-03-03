#!/bin/bash

if [ "$EUID" -ne 0 ]
then
    echo "Please run as root"
    exit
fi

omd_site=$1
api_token=$2
bot_password=$3

telegram_plus_dir=/omd/sites/$omd_site/local/share/checkmk-telegram-plus
telegram_plus_service_name=checkmk-telegram-plus-$omd_site.service

programs=(git runuser pip sed)

for program in "${programs[@]}"; do
    if ! command -v "$program" > /dev/null 2>&1; then
        echo "The installation was stopped by missing programmes. Please install: $program"
        exit
    fi
done

mkdir $telegram_plus_dir

pip install --target=$telegram_plus_dir python-telegram-bot python-telegram-bot[job-queue] python-telegram-bot[callback-data] watchdog

git clone https://github.com/deexno/checkmk-telegram-plus.git
cd checkmk-telegram-plus

sed -i "s|<omd_site>|$omd_site|g" resources/*
sed -i "s|<api_token>|$api_token|g" resources/*
sed -i "s|<password_for_authentication>|$bot_password|g" resources/*
sed -i "s|<telegram_plus_dir>|$telegram_plus_dir|g" resources/*

cp -n resources/config.ini $telegram_plus_dir
cp resources/telegram_bot.py $telegram_plus_dir
cp resources/checkmk-telegram-plus.service /etc/systemd/system/$telegram_plus_service_name

chown -R $omd_site:$omd_site $telegram_plus_dir
chmod -R 755 $telegram_plus_dir

systemctl daemon-reload
systemctl enable --now $telegram_plus_service_name

cp resources/telegram_plus_notify_listener /omd/sites/$omd_site/local/share/check_mk/notifications/
chown $omd_site:$omd_site /omd/sites/$omd_site/local/share/check_mk/notifications/telegram_plus_notify_listener
chmod 755 /omd/sites/$omd_site/local/share/check_mk/notifications/telegram_plus_notify_listener

echo "THE INSTALLATION HAS BEEN COMPLETED. NOW CREATE A NOTIFICATION RULE AS EXPLAINED IN THE GIT REPOSITORY."
