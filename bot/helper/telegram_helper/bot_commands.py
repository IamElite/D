from ...core.config_manager import Config

_ALL_SUFFIX_ALIASES = {"ra", "aa", "uaa", "asa", "rsa", "bsa", "sa", "sta", "usa"}


class BotCommands:
    StartCommand = "start"
    LoginCommand = "login"

    commands = {
        "Mirror": ["mirror", "m"],
        "QbMirror": ["qbmirror", "qm"],
        "JdMirror": ["jdmirror", "jm"],
        "Ytdl": ["ytdl", "y"],
        "Leech": ["leech", "l"],
        "QbLeech": ["qbleech", "ql"],
        "JdLeech": ["jdleech", "jl"],
        "YtdlLeech": ["ytdlleech", "yl"],
        "Clone": ["clone", "cl"],
        "Count": "count",
        "Delete": "del",
        "List": "list",
        "Search": "search",
        "Users": "users",
        "CancelTask": ["cancel", "c"],
        "CancelAll": ["cancelall", "call"],
        "ForceStart": ["forcestart", "fs"],
        "Status": ["status", "s", "statusall", "sa"],
        "MediaInfo": ["mediainfo", "mi"],
        "SpeedTest": ["speedtest", "stest", "speedtestall", "sta"],
        "Ping": "ping",
        "Restart": ["restart", "r", "restartall", "ra"],
        "RestartSessions": ["restartses", "rses"],
        "Broadcast": ["broadcast", "bc"],
        "Stats": ["stats", "st"],
        "Help": ["help", "h"],
        "Log": "log",
        "Shell": "shell",
        "AExec": "aexec",
        "Exec": "exec",
        "ClearLocals": "clearlocals",
        "IMDB": "imdb",
        "Rss": "rss",
        "Authorize": ["authorize", "a", "authorizeall", "aa"],
        "UnAuthorize": ["unauthorize", "ua", "unauthorizeall", "uaa"],
        "AddSudo": ["addsudo", "as", "addsudoall", "asa"],
        "RmSudo": ["rmsudo", "rs", "rmsudoall", "rsa"],
        "BotSet": ["bsetting", "bs", "bsettingall", "bsa"],
        "UserSet": ["usetting", "us", "usettingsall", "usall", "usa"],
        "Select": ["select", "sel"],
    }

    for key, cmds in commands.items():
        vars()[f"{key}Command"] = (
            [
                (
                    f"{cmd}{Config.CMD_SUFFIX}"
                    if not (cmd.endswith("all") or cmd in _ALL_SUFFIX_ALIASES) and cmd != ""
                    else cmd
                )
                for cmd in cmds
                if cmd != ""
            ]
            if isinstance(cmds, list)
            else f"{cmds}{Config.CMD_SUFFIX}"
        )