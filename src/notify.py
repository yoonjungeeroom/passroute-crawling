"""DLQ 알람 → Discord 웹훅 알림 Lambda 핸들러."""

import json
import logging
import os
import urllib.request

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def discord_notifier(event, _context):
    """SNS 메시지를 받아 Discord 웹훅으로 전송한다."""
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        logger.error("DISCORD_WEBHOOK_URL 환경변수 누락")
        return

    for record in event.get("Records", []):
        sns_message = record.get("Sns", {})
        subject = sns_message.get("Subject", "알람")
        raw_message = sns_message.get("Message", "")

        try:
            alarm = json.loads(raw_message)
            alarm_name = alarm.get("AlarmName", "")
            description = alarm.get("AlarmDescription", "")
            reason = alarm.get("NewStateReason", "")
            region = alarm.get("Region", "")
            timestamp = alarm.get("StateChangeTime", "")

            embed = {
                "title": f"\u26a0\ufe0f {alarm_name}",
                "description": description,
                "color": 0xFF4444,
                "fields": [
                    {"name": "\uc6d0\uc778", "value": reason, "inline": False},
                    {"name": "\ub9ac\uc804", "value": region, "inline": True},
                    {"name": "\ubc1c\uc0dd \uc2dc\uac01", "value": timestamp, "inline": True},
                ],
            }
            payload = {"embeds": [embed]}
        except (json.JSONDecodeError, KeyError):
            payload = {
                "content": f"**{subject}**\n```\n{raw_message[:1500]}\n```",
            }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            webhook_url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "passroute-dlq-notifier/1.0",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                logger.info("Discord 알림 전송 완료: status=%d", resp.status)
        except Exception:
            logger.exception("Discord 웹훅 전송 실패")
            raise
