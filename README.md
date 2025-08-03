# Endlessh Journal Analyzer

[endlessh](https://github.com/skeeto/endlessh) is an SSH tarpit that can be used to couteract automated SSH brute force attacks.
As a sysadmin, you might not only want to piss off attackers, but you might also be interested how many attacks got stuck.

The `analyze.py` script is a very simple Python script that uses your `journalctl` log to parse the `endlessh` log messages and print a nice summary about attackers that got stuck in the tarpit:

```bash
# Shows open connections with their IP Address and creation time
Currently open connections:
        39.X.X.99 since 2025-08-03 18:30:18.978000+00:00

# Shows closed connections grouped by IP address
Closed connections: 70
80.X.X.138: 53 connections, spent 22 minute(s), 0 second(s)
20.X.X.33: 2 connectionis, spent 40 second(s)
...
```

This script is far from being as sophisticated as the [go version](https://github.com/shizunge/endlessh-go) of endlessh, which includes prometheus metrics that can be visualized using graphana.
Instead, it is aimed towards minimal and simple deployments.

## Usage

The only external dependency of this script is [python-systemd](https://github.com/systemd/python-systemd) which might already be installed on your system.
Otherwise, install it using your systems package manager

**Do not use** ~~pip install python-systemd~~, this is another package!

Running `./analyze.py -h` should give you a good understanding how to use this tool.

If your service is not named `endlessh`, you can customize the name using `--unit yourname.service`.
If `endlessh` is running in unprivileged mode, you can specify the `--user` flag (equal to `journalctl --user`) to retrieve the logs.

Finally, the date range is specified.
You can either use a custom range by specifying `--start/--end` in the given format (see the `./analyze.py --help`), or you can use a customized preset, e.g. `--today` or `--yesterday`.

## Geolocation

To properly lookup geo information, a geolocation database is required.
For now, the `-g/--geo-ip` flag allows using the [ipinfo.io](https://ipinfo.io) API to add simple geolocation information to the output:

```bash
Closed connections: 83
80.X.X.X AS39612 Tevia Ltd. (Moscow, RU): 53 connections, spent 22 minute(s), 0 second(s)
3.X.X.X scan.cypex.ai AS16509 Amazon.com, Inc. (Ohio, US): 6 connections, spent 2 minute(s), 0 second(s)
```
