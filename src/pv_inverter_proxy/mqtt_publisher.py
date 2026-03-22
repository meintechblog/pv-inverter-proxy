"""MQTT publisher with queue-based decoupling, LWT, HA discovery, and change detection.

Consumes messages from ctx.mqtt_pub_queue and publishes to the configured broker.
Completely independent from venus_reader.py (per D-03).
"""
from __future__ import annotations

import asyncio
import json
import time

import aiomqtt
import structlog

log = structlog.get_logger(component="mqtt_publisher")


async def mqtt_publish_loop(ctx, config, inverters=None, virtual_name="") -> None:
    """Background task: consume from queue, publish to MQTT broker.

    Args:
        ctx: AppContext with mqtt_pub_queue, mqtt_pub_connected, shutdown_event
        config: MqttPublishConfig with host, port, topic_prefix, client_id, interval_s
        inverters: Optional list of InverterEntry objects for HA discovery
        virtual_name: Optional virtual inverter name for HA discovery
    """
    queue = ctx.mqtt_pub_queue
    backoff = 1.0
    max_backoff = 30.0

    while not ctx.shutdown_event.is_set():
        try:
            will = aiomqtt.Will(
                topic=f"{config.topic_prefix}/status",
                payload="offline",
                qos=1,
                retain=True,
            )
            async with aiomqtt.Client(
                hostname=config.host,
                port=config.port,
                identifier=config.client_id,
                will=will,
                keepalive=30,
            ) as client:
                # Announce online (per D-06)
                await client.publish(
                    f"{config.topic_prefix}/status",
                    payload="online",
                    qos=1,
                    retain=True,
                )
                ctx.mqtt_pub_connected = True
                backoff = 1.0  # reset on successful connect
                log.info("mqtt_pub_connected", host=config.host, port=config.port)

                # Publish HA discovery configs once on connect (per D-13)
                if inverters:
                    from pv_inverter_proxy.mqtt_payloads import (
                        ha_discovery_configs,
                        ha_discovery_topic,
                        virtual_ha_discovery_configs,
                    )
                    for inv in inverters:
                        if not inv.enabled:
                            continue
                        configs = ha_discovery_configs(inv.id, config.topic_prefix, inv)
                        for idx, disc_cfg in enumerate(configs):
                            # Use ha_discovery_topic to generate topic from field key
                            from pv_inverter_proxy.mqtt_payloads import SENSOR_DEFS
                            field_key = SENSOR_DEFS[idx][1]
                            topic = ha_discovery_topic(inv.id, field_key)
                            await client.publish(
                                topic,
                                payload=json.dumps(disc_cfg),
                                qos=1,
                                retain=True,
                            )
                        # Device availability
                        await client.publish(
                            f"{config.topic_prefix}/device/{inv.id}/availability",
                            payload="online",
                            qos=1,
                            retain=True,
                        )
                    # Virtual device discovery
                    if virtual_name:
                        v_configs = virtual_ha_discovery_configs(
                            config.topic_prefix, virtual_name
                        )
                        for disc_cfg in v_configs:
                            field_key = disc_cfg.get("value_template", "").split(".")[-1].rstrip(" }}")
                            topic = ha_discovery_topic("virtual", field_key)
                            await client.publish(
                                topic,
                                payload=json.dumps(disc_cfg),
                                qos=1,
                                retain=True,
                            )
                        await client.publish(
                            f"{config.topic_prefix}/virtual/availability",
                            payload="online",
                            qos=1,
                            retain=True,
                        )

                    log.info("mqtt_ha_discovery_published",
                             devices=len([i for i in inverters if i.enabled]),
                             virtual=bool(virtual_name))

                # Consume from queue and publish with change detection
                last_payloads: dict[str, str] = {}

                while not ctx.shutdown_event.is_set():
                    try:
                        msg = await asyncio.wait_for(queue.get(), timeout=config.interval_s)
                    except asyncio.TimeoutError:
                        continue

                    msg_type = msg.get("type")

                    if msg_type == "device":
                        from pv_inverter_proxy.mqtt_payloads import device_payload
                        payload = device_payload(msg["snapshot"], device_name=msg.get("device_name", ""))
                        payload_json = json.dumps(payload, separators=(",", ":"))
                        device_id = msg["device_id"]

                        # Change detection (D-05 / PUB-04)
                        if last_payloads.get(device_id) == payload_json:
                            ctx.mqtt_pub_skipped += 1
                            continue  # Skip identical payload

                        last_payloads[device_id] = payload_json
                        topic = f"{config.topic_prefix}/device/{device_id}/state"
                        await client.publish(topic, payload=payload_json, qos=0, retain=True)
                        ctx.mqtt_pub_messages += 1
                        ctx.mqtt_pub_bytes += len(payload_json)
                        ctx.mqtt_pub_last_ts = time.time()

                    elif msg_type == "virtual":
                        from pv_inverter_proxy.mqtt_payloads import virtual_payload
                        payload = virtual_payload(msg["virtual_data"])
                        payload_json = json.dumps(payload, separators=(",", ":"))

                        if last_payloads.get("__virtual__") == payload_json:
                            ctx.mqtt_pub_skipped += 1
                            continue

                        last_payloads["__virtual__"] = payload_json
                        topic = f"{config.topic_prefix}/virtual/state"
                        await client.publish(topic, payload=payload_json, qos=0, retain=True)
                        ctx.mqtt_pub_messages += 1
                        ctx.mqtt_pub_bytes += len(payload_json)
                        ctx.mqtt_pub_last_ts = time.time()

                    else:
                        # Legacy format: topic + payload (backward compatibility)
                        topic = msg.get("topic", "")
                        payload = msg.get("payload", {})
                        await client.publish(topic, payload=json.dumps(payload), qos=0)

        except aiomqtt.MqttError as e:
            ctx.mqtt_pub_connected = False
            log.warning("mqtt_pub_disconnected", error=str(e), backoff=backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)
        except asyncio.CancelledError:
            break

    ctx.mqtt_pub_connected = False
    log.info("mqtt_pub_stopped")
