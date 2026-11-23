#!/bin/sh
# Put the official 1.16.1 server.jar in this folder first. Raise -Xmx if you have the RAM.
exec java -Xms4G -Xmx8G -XX:+UseG1GC -jar server.jar nogui
