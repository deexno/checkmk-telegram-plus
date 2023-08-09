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
                f.write(
                    f"{item['event']};;"
                    f"{item['id']};;"
                    f"{item['priority']};;"
                    f"{item['created']}\n"
                )

    def update_queue(self):
        if not os.path.exists(self.file_path):
            self.queue = []
            self.store_queue()
        else:
            self.queue = []
            with open(self.file_path, "r", encoding="utf-8") as f:
                for line in f:
                    event, item_id, priority, created = line.strip().split(
                        ";;"
                    )
                    self.queue.append(
                        {
                            "event": event,
                            "id": item_id,
                            "priority": priority,
                            "created": created,
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
        }
        self.queue.insert(0, new_item)
        self.store_queue()

    def drop_item(self, item_id):
        self.queue = [item for item in self.queue if item["id"] != item_id]
        self.store_queue()
