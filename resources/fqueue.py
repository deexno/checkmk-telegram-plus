import os
import uuid
from datetime import datetime

import pandas as pd


class Queue(object):
    def __init__(self, file_path, order_by="created", ascending=True) -> None:
        self.file_path = file_path
        self.order_by = order_by
        self.ascending = ascending

        self.update_queue()

    def store_queue(self):
        self.queue.to_csv(
            self.file_path, encoding="utf-8", sep="|", index=False
        )

    def update_queue(self):
        if not os.path.exists(self.file_path):
            queue_columns = ["event", "id", "priority", "created"]
            self.queue = pd.DataFrame([], columns=queue_columns)
            self.store_queue()
        else:
            self.queue = pd.read_csv(self.file_path, sep="|")

        self.queue = self.queue.sort_values(
            by=self.order_by, ascending=self.ascending
        )

    def get_queue(self):
        self.update_queue()
        return self.queue

    def add_item(self, event, priority=0):
        self.queue = pd.concat(
            [
                pd.DataFrame(
                    {
                        "event": [event],
                        "id": [uuid.uuid1()],
                        "priority": [priority],
                        "created": [datetime.now()],
                    }
                ),
                self.queue,
            ]
        ).reset_index(drop=True)

        self.store_queue()

    def drop_item(self, id):
        self.queue = self.queue[self.queue["id"] != id]
        self.store_queue()
