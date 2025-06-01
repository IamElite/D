from speedtest import Speedtest, ConfigRetrievalError, SpeedtestException

from .. import LOGGER
from ..helper.telegram_helper.message_utils import (
    send_message,
    edit_message,
    delete_message,
)
from ..helper.ext_utils.bot_utils import new_task, sync_to_async
from ..helper.ext_utils.status_utils import get_readable_file_size


@new_task
async def speedtest(_, message):
    speed_msg = await send_message(message, "<i>Initiating Speedtest...</i>")
    try:
        speedtest = await sync_to_async(Speedtest)
        await edit_message(speed_msg, "<i>Finding best server...</i>")
        best_server = await sync_to_async(speedtest.get_best_server)
        server_info = best_server or speedtest.get_best_server()
        await edit_message(speed_msg, "<i>Testing download speed...</i>")
        await sync_to_async(speedtest.download)
        await edit_message(speed_msg, "<i>Testing upload speed...</i>")
        await sync_to_async(speedtest.upload)
        await edit_message(speed_msg, "<i>Sharing results...</i>")
        await sync_to_async(speedtest.results.share)
        result = speedtest.results.dict()
    except ConfigRetrievalError:
        await edit_message(
            speed_msg,
            "<b>ERROR:</b> <i>Can't connect to Speedtest server at the moment. Try again later!</i>"
        )
        return
    except SpeedtestException as e:
        await edit_message(speed_msg, f"<b>Speedtest Error:</b> <code>{str(e)}</code>")
        return
    except Exception as e:
        LOGGER.error(f"Speedtest failed: {e}")
        await edit_message(speed_msg, f"<b>Unexpected Error:</b> <code>{str(e)}</code>")
        return

    def safe_get(d, *keys, default="N/A"):
        for k in keys:
            d = d.get(k, {}) if isinstance(d, dict) else {}
        return d or default

    upload_speed = get_readable_file_size(result.get('upload', 0) / 8) + "/s"
    download_speed = get_readable_file_size(result.get('download', 0) / 8) + "/s"
    ping = result.get('ping', 'N/A')
    timestamp = result.get('timestamp', 'N/A')
    bytes_sent = get_readable_file_size(int(result.get('bytes_sent', 0)))
    bytes_received = get_readable_file_size(int(result.get('bytes_received', 0)))
    server = result.get('server', {})
    share_url = result.get('share', None)

    string_speed = f"""
➲ <b><i>SPEEDTEST INFO</i></b>
╭ <b>Upload:</b> <code>{upload_speed}</code>
├ <b>Download:</b>  <code>{download_speed}</code>
├ <b>Ping:</b> <code>{ping} ms</code>
├ <b>Time:</b> <code>{timestamp}</code>
├ <b>Data Sent:</b> <code>{bytes_sent}</code>
╰ <b>Data Received:</b> <code>{bytes_received}</code>

➲ <b><i>SPEEDTEST SERVER</i></b>
╭ <b>Name:</b> <code>{server.get('name', 'N/A')}</code>
├ <b>Country:</b> <code>{server.get('country', 'N/A')}, {server.get('cc', 'N/A')}</code>
├ <b>Sponsor:</b> <code>{server.get('sponsor', 'N/A')}</code>
├ <b>Latency:</b> <code>{server.get('latency', 'N/A')}</code>
├ <b>Latitude:</b> <code>{server.get('lat', 'N/A')}</code>
╰ <b>Longitude:</b> <code>{server.get('lon', 'N/A')}</code>
"""

    try:
        await send_message(message, string_speed, photo=share_url if share_url else None)
        await delete_message(speed_msg)
    except Exception as e:
        LOGGER.error(f"Speedtest send_message failed: {e}")
        await edit_message(speed_msg, string_speed)