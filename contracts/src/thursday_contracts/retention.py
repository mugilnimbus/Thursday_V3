"""How long working data is kept: the setting the gateway owns and hands to the other services.

Working data is what a service keeps about how work was done: stored events, saved steps of finished
tasks, tool-call logs. Chats themselves are not working data; they stay until they are deleted.

The gateway sends the setting to each agent with `PUT /v1/retention` (service token). Each service keeps
its own copy, so it prunes correctly while the gateway is down. Sending the same value again changes nothing.
"""

from pydantic import BaseModel, ConfigDict, Field

RETENTION_PATH = "/retention"
KEEP_UNTIL_DELETED = 0
MAX_RETENTION_DAYS = 3650


class RetentionSetting(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days: int = Field(ge=0, le=MAX_RETENTION_DAYS, description="0 keeps working data until it is deleted by hand.")
