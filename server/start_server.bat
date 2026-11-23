@echo off
java -Xms4G -Xmx8G -XX:+UseG1GC -jar server.jar nogui
