import base64
import json
import os
import uuid
from datetime import datetime


class Queue(object):
    def __init__(self, file_path, order_by="created", ascending=True) -> None:
        self.file_path = file_path
        self.order_by = order_by
        self.ascending = ascending

        self.update_queue()

    def store_queue(self):
        with open(self.file_path, "w", encoding="utf-8") as f:
            for item in self.queue:
                payload = item.get("payload")
                payload_b64 = ""
                if payload:
                    payload_json = json.dumps(
                        payload, ensure_ascii=False, separators=(",", ":")
                    )
                    payload_b64 = base64.b64encode(
                        payload_json.encode("utf-8")
                    ).decode("ascii")
                f.write(
                    f"{item['event']}|||"
                    f"{item['id']}|||"
                    f"{item['priority']}|||"
                    f"{item['created']}|||"
                    f"{payload_b64}\n"
                )

    def update_queue(self):
        if not os.path.exists(self.file_path):
            self.queue = []
            self.store_queue()
        else:
            self.queue = []
            with open(self.file_path, "r", encoding="utf-8") as f:
                for line in f:
                    parts = line.rstrip("\n").split("|||")
                    if len(parts) not in {4, 5}:
                        continue
                    event, item_id, priority, created = parts[:4]
                    payload = None
                    if len(parts) == 5 and parts[4]:
                        try:
                            payload = json.loads(
                                base64.b64decode(parts[4]).decode("utf-8")
                            )
                        except Exception:
                            payload = None
                    self.queue.append(
                        {
                            "event": event.replace("\\n", "\n"),
                            "id": item_id,
                            "priority": priority,
                            "created": created,
                            "payload": payload,
                        }
                    )

            self.queue.sort(
                key=lambda item: item[self.order_by],
                reverse=not self.ascending,
            )

    def get_queue(self):
        self.update_queue()
        return self.queue

    def add_item(self, event, priority=0):
        new_item = {
            "event": event,
            "id": str(uuid.uuid1()),
            "priority": priority,
            "created": datetime.now(),
            "payload": None,
        }
        self.queue.insert(0, new_item)
        self.store_queue()

    def drop_item(self, item_id):
        self.queue = [item for item in self.queue if item["id"] != item_id]
        self.store_queue()
