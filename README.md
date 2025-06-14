# hwwwmon: Remote real-time web-based hardware monitoring

hwwwmon lets you monitor fan speed / temperature through a remote web browser.

The intended scenario is viewing a Linux (read: [Bazzite](https://bazzite.gg/)) gaming PC's stats whilst a game is being played,
viewing the stats in a web browser.

## Installation

The script has no dependencies other than python3(*), download / clone the repository, and run it:

```shell
git clone https://github.com/lentinj/hwwwmon
./hwwwmon/hwwwmon.py
```

(*) [Chart.js](https://www.chartjs.org/) is used for charting, fetched from cdnjs.cloudflare.com.

## Limitations

The web-server only supports one active connection at a time.
If you want to connect from elsewhere, close the old browser tab or press stop.
