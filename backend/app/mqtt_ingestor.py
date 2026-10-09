"""
EnergyPilot MQTT telemetry ingestor.

MQTT topic
----------

    building/<building_id>/meter

Example:

    building/building-001/meter

MQTT payload
------------

{
    "building_id": "building-001",
    "timestamp": "2026-10-07T18:00:00Z",
    "demand_kw": 4.82,
    "energy_kwh": 2.41,
    "temperature_c": 18.4,
    "occupancy": 3,
    "hvac_kw": 1.72,
    "lighting_kw": 0.64
}

The payload is validated by models.TelemetryReading and then inserted
through app.db.insert_reading().
"""

from __future__ import annotations

import json
import logging
import signal
import sys
from typing import Any

import paho.mqtt.client as mqtt

from app.db import init_db, insert_reading
from config import (
    MQTT_CLIENT_ID,
    MQTT_HOST,
    MQTT_KEEPALIVE,
    MQTT_PASSWORD,
    MQTT_QOS,
    MQTT_STATUS_TOPIC,
    MQTT_TLS_CA_CERT,
    MQTT_TLS_ENABLED,
    MQTT_TOPIC,
    MQTT_USERNAME,
)
from models import (
    TelemetryReading,
    TelemetryValidationError,
)


# ============================================================================
# Logging
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s | "
        "%(levelname)s | "
        "%(name)s | "
        "%(message)s"
    ),
)

logger = logging.getLogger(
    "energypilot.mqtt"
)


# ============================================================================
# Ingestor
# ============================================================================

class MQTTIngestor:
    """
    MQTT -> TelemetryReading -> PostgreSQL pipeline.
    """

    def __init__(self) -> None:

        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=MQTT_CLIENT_ID,
            clean_session=True,
        )

        self.running = True

        self.received_count = 0
        self.inserted_count = 0
        self.rejected_count = 0

        # ------------------------------------------------------------
        # Authentication
        # ------------------------------------------------------------

        if MQTT_USERNAME:
            self.client.username_pw_set(
                MQTT_USERNAME,
                MQTT_PASSWORD,
            )

        # ------------------------------------------------------------
        # TLS
        # ------------------------------------------------------------

        if MQTT_TLS_ENABLED:

            if MQTT_TLS_CA_CERT:
                self.client.tls_set(
                    ca_certs=MQTT_TLS_CA_CERT
                )
            else:
                self.client.tls_set()

        # ------------------------------------------------------------
        # MQTT callbacks
        # ------------------------------------------------------------

        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message
        self.client.on_subscribe = self.on_subscribe
        self.client.on_log = self.on_log

        # ------------------------------------------------------------
        # Last Will
        # ------------------------------------------------------------

        self.client.will_set(
            MQTT_STATUS_TOPIC,
            payload=json.dumps(
                {
                    "status": "offline",
                    "client_id": MQTT_CLIENT_ID,
                }
            ),
            qos=MQTT_QOS,
            retain=True,
        )

    # ========================================================================
    # MQTT connection
    # ========================================================================

    def on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: mqtt.Properties | None,
    ) -> None:

        if reason_code != 0:

            logger.error(
                "MQTT connection failed: %s",
                reason_code,
            )

            return

        logger.info(
            "Connected to MQTT broker %s:%s",
            MQTT_HOST,
            self._mqtt_port(),
        )

        result, _ = client.subscribe(
            MQTT_TOPIC,
            qos=MQTT_QOS,
        )

        if result != mqtt.MQTT_ERR_SUCCESS:

            logger.error(
                "Failed to subscribe to MQTT topic %s: %s",
                MQTT_TOPIC,
                mqtt.error_string(result),
            )

            return

        self._publish_status(
            "online"
        )

        logger.info(
            "Subscribed to MQTT topic: %s",
            MQTT_TOPIC,
        )

    def on_subscribe(
        self,
        client: mqtt.Client,
        userdata: Any,
        mid: int,
        reason_codes: list[mqtt.ReasonCode],
        properties: mqtt.Properties | None,
    ) -> None:

        logger.info(
            "MQTT subscription acknowledged: mid=%s reason=%s",
            mid,
            reason_codes,
        )

    def on_disconnect(
        self,
        client: mqtt.Client,
        userdata: Any,
        disconnect_flags: mqtt.DisconnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: mqtt.Properties | None,
    ) -> None:

        logger.warning(
            "Disconnected from MQTT broker: %s",
            reason_code,
        )

    # ========================================================================
    # MQTT message processing
    # ========================================================================

    def on_message(
        self,
        client: mqtt.Client,
        userdata: Any,
        message: mqtt.MQTTMessage,
    ) -> None:

        self.received_count += 1

        try:

            payload = self._decode_payload(
                message.payload
            )

            reading = TelemetryReading.from_dict(
                payload
            )

            topic_building_id = (
                self._building_id_from_topic(
                    message.topic
                )
            )

            if topic_building_id is not None:

                if (
                    reading.building_id
                    != topic_building_id
                ):
                    raise TelemetryValidationError(
                        "building_id does not match "
                        "the MQTT topic."
                    )

            insert_reading(
                reading,
                source="mqtt",
            )

            self.inserted_count += 1

            logger.info(
                "Inserted telemetry: "
                "building=%s timestamp=%s "
                "demand=%.3f kW energy=%.3f kWh",
                reading.building_id,
                reading.timestamp,
                reading.demand_kw,
                reading.energy_kwh,
            )

        except TelemetryValidationError as exc:

            self.rejected_count += 1

            logger.warning(
                "Rejected MQTT telemetry from %s: %s",
                message.topic,
                exc,
            )

        except json.JSONDecodeError as exc:

            self.rejected_count += 1

            logger.warning(
                "Invalid JSON from MQTT topic %s: %s",
                message.topic,
                exc,
            )

        except Exception:

            self.rejected_count += 1

            logger.exception(
                "Failed to process MQTT message "
                "from topic %s",
                message.topic,
            )

    # ========================================================================
    # Payload handling
    # ========================================================================

    @staticmethod
    def _decode_payload(
        payload_bytes: bytes,
    ) -> dict[str, Any]:

        try:
            payload_text = payload_bytes.decode(
                "utf-8"
            )
        except UnicodeDecodeError as exc:
            raise TelemetryValidationError(
                "MQTT payload must be UTF-8."
            ) from exc

        payload = json.loads(
            payload_text
        )

        if not isinstance(payload, dict):
            raise TelemetryValidationError(
                "MQTT telemetry payload must be a JSON object."
            )

        return payload

    @staticmethod
    def _building_id_from_topic(
        topic: str,
    ) -> str | None:

        parts = topic.strip("/").split("/")

        if len(parts) != 3:
            return None

        if parts[0] != "building":
            return None

        if parts[2] != "meter":
            return None

        building_id = parts[1].strip()

        return building_id or None

    # ========================================================================
    # Status
    # ========================================================================

    def _publish_status(
        self,
        status: str,
    ) -> None:

        payload = {
            "status": status,
            "client_id": MQTT_CLIENT_ID,
            "received_count": self.received_count,
            "inserted_count": self.inserted_count,
            "rejected_count": self.rejected_count,
        }

        result = self.client.publish(
            MQTT_STATUS_TOPIC,
            json.dumps(payload),
            qos=MQTT_QOS,
            retain=True,
        )

        if result.rc != mqtt.MQTT_ERR_SUCCESS:

            logger.warning(
                "Failed to publish MQTT status: %s",
                mqtt.error_string(result.rc),
            )

    # ========================================================================
    # Lifecycle
    # ========================================================================

    def start(self) -> None:

        logger.info(
            "Starting EnergyPilot MQTT ingestor."
        )

        logger.info(
            "MQTT broker: %s:%s",
            MQTT_HOST,
            self._mqtt_port(),
        )

        logger.info(
            "MQTT topic: %s",
            MQTT_TOPIC,
        )

        logger.info(
            "Database initialization..."
        )

        init_db()

        logger.info(
            "Database ready."
        )

        try:

            self.client.connect_async(
                MQTT_HOST,
                self._mqtt_port(),
                MQTT_KEEPALIVE,
            )

            logger.info(
                "Starting MQTT network loop."
            )

            self.client.loop_forever(
                retry_first_connection=True
            )

        except KeyboardInterrupt:

            logger.info(
                "Keyboard interrupt received."
            )

        except Exception:

            logger.exception(
                "MQTT ingestor stopped unexpectedly."
            )

            raise

        finally:

            self.stop()

    def stop(self) -> None:

        if not self.running:
            return

        self.running = False

        logger.info(
            "Stopping EnergyPilot MQTT ingestor."
        )

        try:
            self._publish_status(
                "offline"
            )
        except Exception:
            logger.exception(
                "Unable to publish offline status."
            )

        try:
            self.client.disconnect()
        except Exception:
            logger.exception(
                "Error while disconnecting MQTT client."
            )

        logger.info(
            "MQTT ingestor stopped. "
            "received=%s inserted=%s rejected=%s",
            self.received_count,
            self.inserted_count,
            self.rejected_count,
        )

    # ========================================================================
    # Helpers
    # ========================================================================

    @staticmethod
    def _mqtt_port() -> int:
        """
        Return the configured MQTT port.

        Kept as a small method to make broker configuration explicit.
        """

        from config import MQTT_PORT

        return MQTT_PORT

    @staticmethod
    def on_log(
        client: mqtt.Client,
        userdata: Any,
        level: int,
        buf: str,
    ) -> None:

        if level == mqtt.MQTT_LOG_ERR:
            logger.error(
                "Paho MQTT: %s",
                buf,
            )

        elif level == mqtt.MQTT_LOG_WARNING:
            logger.warning(
                "Paho MQTT: %s",
                buf,
            )


# ============================================================================
# Signal handling
# ============================================================================

_ingestor: MQTTIngestor | None = None


def _handle_shutdown(
    signum: int,
    frame: Any,
) -> None:

    logger.info(
        "Shutdown signal received: %s",
        signum,
    )

    if _ingestor is not None:
        _ingestor.stop()

    sys.exit(0)


signal.signal(
    signal.SIGINT,
    _handle_shutdown,
)

signal.signal(
    signal.SIGTERM,
    _handle_shutdown,
)


# ============================================================================
# Main
# ============================================================================

def main() -> None:

    global _ingestor

    _ingestor = MQTTIngestor()

    _ingestor.start()


if __name__ == "__main__":
    main()