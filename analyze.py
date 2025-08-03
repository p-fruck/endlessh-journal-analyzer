#!/usr/bin/env python3

import argparse
import ipaddress
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, time, timezone
from enum import Enum
import urllib.request

from systemd import journal
from typing import Iterable

DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%S"


class ConnectionType(Enum):
    UNKNOWN = 0
    ACCEPT = 1
    CLOSE = 2


@dataclass
class ConnectionEvent:
    time: datetime
    type: ConnectionType
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address
    fd: int
    duration: None | float

    def conn(self):
        """Identify the current connection"""
        return (self.ip, self.fd)

    @classmethod
    def from_journal(cls, msg: str):
        """Create dataclass instance from journal message"""
        split = msg.split(" ")
        if len(split) < 6:
            return

        if not split[2].startswith("host="):
            return

        ip = ipaddress.ip_address(split[2].split("=")[1])
        fd = int(split[4].split("=")[1])
        duration = None

        match split[1]:
            case "ACCEPT":
                type = ConnectionType.ACCEPT
            case "CLOSE":
                type = ConnectionType.CLOSE
                duration = float(split[5].split("=")[1])
            case _:
                print(f"Unmatched connection type {split[1]}")
                type = ConnectionType.UNKNOWN

        time = datetime.strptime(split[0], "%Y-%m-%dT%H:%M:%S.%fZ")
        time = time.replace(tzinfo=timezone.utc)

        return cls(time=time, type=type, ip=ip, fd=fd, duration=duration)


@dataclass
class Connection:
    events: list[ConnectionEvent]

    def add_event(self, event: ConnectionEvent):
        if not self.events:
            self.events = [event]
        else:
            if self.events[-1].ip != event.ip:
                raise ValueError("Invalid IP for connection!")
            if self.events[-1].fd != event.fd:
                raise ValueError("Invalid fd for connection!")
            self.events.append(event)

    def get_ip(self):
        return self.events[0].ip

    def get_duration(self) -> float | None:
        return self.events[-1].duration


def get_today_timestamps():
    today = datetime.now()
    start = datetime.combine(today.date(), time.min)
    end = datetime.combine(today.date(), time.max)
    return int(start.timestamp()), int(end.timestamp())


def get_yesterday_timestamps():
    yesterday = datetime.now().date() - timedelta(days=1)
    start = datetime.combine(yesterday, time.min)
    end = datetime.combine(yesterday, time.max)
    return int(start.timestamp()), int(end.timestamp())


def parse_datetime(dt_str):
    try:
        return datetime.strptime(dt_str, DATETIME_FORMAT)
    except ValueError:
        raise ValueError(f"Datetime '{dt_str}' does not match format {DATETIME_FORMAT}")


def parse_arguments():
    parser = argparse.ArgumentParser(description="Create summary of the endlessh log")
    parser.add_argument(
        "-u", "--unit", type=str, help="The systemd unit name (default: endlessh.service)", default="endlessh.service"
    )
    parser.add_argument("-U", "--user", action="store_true", help="Execute for current user instead of system")
    parser.add_argument("-g", "--geo-ip", action="store_true", help="Look up the geo ip information")

    # time range arguments/presets
    parser.add_argument("--start", type=str, help="Start datetime (e.g., 2025-08-01T00:00:00)")
    parser.add_argument("--end", type=str, help="End datetime (e.g., 2025-08-02T00:00:00)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--today", action="store_true", help="Use today's full date range")
    group.add_argument("--yesterday", action="store_true", help="Use yesterday's full date range")

    args = parser.parse_args()

    # Validate start/end or presets are specified and mutually exclusive
    if args.today or args.yesterday:
        if args.start is not None or args.end is not None:
            parser.error("When using --today or --yesterday, you cannot specify --start or --end")

    else:
        if args.start is None or args.end is None:
            parser.error("You must specify both --start and --end if not using --today or --yesterday")

    return args


def resolve_time_range(args):
    if args.today:
        return get_today_timestamps()
    elif args.yesterday:
        return get_yesterday_timestamps()
    else:
        start_dt = parse_datetime(args.start)
        end_dt = parse_datetime(args.end)
        return int(start_dt.timestamp()), int(end_dt.timestamp())


def yield_journal_messages(start_time: int, end_time: int, unit: str, user: bool) -> Iterable[str]:
    if user:
        j = journal.Reader(journal.CURRENT_USER)
        j.add_match(_SYSTEMD_USER_UNIT=unit)
    else:
        j = journal.Reader()
        j.add_match(_SYSTEMD_UNIT=unit)

    j.seek_realtime(start_time)
    j.get_next()  # Move to the first entry on/after start_time

    while True:
        entry = j.get_next()
        if not entry:
            break
        realtime = entry["__REALTIME_TIMESTAMP"]  # This is a datetime.datetime object

        if int(realtime.timestamp()) > end_time:
            break

        yield entry.get("MESSAGE", "<no message>")


def human_readable_seconds(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} second(s)"
    elif seconds < 3600:
        minutes = seconds // 60
        rem = seconds % 60
        return f"{minutes} minute(s), {rem} second(s)"
    else:
        hours = seconds // 3600
        rem = seconds % 3600
        minutes = rem // 60
        rem_seconds = rem % 60
        return f"{hours} hour(s), {minutes} minute(s), {rem_seconds} second(s)"


def get_geoip_info(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> dict:
    ip_str = str(ip)
    if "." in ip_str and ":" in ip_str:
        # convert ipv4-mapped-ipv6-address to regular v6
        ip_str = ip_str.split(":")[-1]

    with urllib.request.urlopen(f"https://ipinfo.io/{ip_str}") as response:
        return json.loads(response.read().decode())


def main():
    args = parse_arguments()
    try:
        start_time, end_time = resolve_time_range(args)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    closed_connections = []
    open_connections = {}
    for msg in yield_journal_messages(start_time, end_time, args.unit, args.user):
        if not (event := ConnectionEvent.from_journal(msg)):
            continue
        if event.type == ConnectionType.ACCEPT:
            if conn := open_connections.get(event.conn()):
                conn.add_event(event)
            else:
                conn = Connection([event])
                open_connections[event.conn()] = conn

        if event.type == ConnectionType.CLOSE:
            if not (connection := open_connections[event.conn()]):
                print(f"Closing leftover connection: {event=}", file=sys.stderr)
            else:
                connection.add_event(event)
                closed_connections.append(connection)
                del open_connections[event.conn()]

    if open_connections:
        print("")
        print("Currently open connections:")
    for event in open_connections:
        print(f"\t{event=}")

    print("")
    print(f"Closed connections: {len(closed_connections)}")

    grouped_connections = {}
    for conn in closed_connections:
        if conn.get_ip() in grouped_connections:
            grouped_connections[conn.get_ip()].append(conn)
        else:
            grouped_connections[conn.get_ip()] = [conn]

    # order by ip with most connections
    for conns in reversed(sorted(grouped_connections.values(), key=len)):
        ip = conns[0].get_ip()
        duration = sum(conn.get_duration() for conn in conns)

        msg = f"{ip}"
        if args.geo_ip:
            geoip_info = get_geoip_info(ip)
            if "hostname" in geoip_info:
                msg += f" {geoip_info['hostname']}"
            if "org" in geoip_info:
                msg += f" {geoip_info['org']}"
            if "region" in geoip_info:
                msg += f" ({geoip_info['region']}, {geoip_info.get('country', '?')})"

        print(f"{msg}: {len(conns)} connections, spent {human_readable_seconds(int(duration))}")


if __name__ == "__main__":
    main()
