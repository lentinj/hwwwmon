#!/usr/bin/python3
import argparse
import glob
import http.server
import json
import os.path
import re
import socket
from string import Template
import time
import urllib.parse

mons = dict()

def init_mon():
    def slurp(path, ifnotexist=""):
        if not os.path.exists(path):
            return ifnotexist
        with open(path, "r") as f:
            return f.read().strip()

    for mon_path in sorted(glob.glob("/sys/class/hwmon/*/*_input")):
        mon_type = re.sub(r'\d.*', '', os.path.basename(mon_path))
        mon_name = " ".join((
            slurp(os.path.join(os.path.dirname(mon_path), "name")),
            slurp(re.sub(r'_input$', '_label', mon_path), ifnotexist=re.sub(r'_input$', '', os.path.basename(mon_path))),
        ))

        if mon_type not in mons:
            mons[mon_type] = dict()
        mons[mon_type][mon_path] = dict(
            name=mon_name,
            fh=open(mon_path, 'r'),
        )

def collect_mon():
    out = dict(_errors=[])
    for mon_type in mons.keys():
        out[mon_type] = dict()
        for mon_path, m in mons[mon_type].items():
            m['fh'].seek(0)
            try:
                val = int(m['fh'].read())
                if mon_type == 'temp' or mon_type == 'in':
                    val = val / 1000
                out[mon_type][m['name']] = val
            except OSError:
                out['_errors'].append("Failed to read %s" % mon_path)
    return out

class HwmRequestHandler(http.server.SimpleHTTPRequestHandler):
    # https://docs.python.org/3/library/http.server.html#http.server.BaseHTTPRequestHandler

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(u.query)

        if u.path == "/":
            return self.do_index()
        if u.path == "/mon.json":
            return self.do_mon()
        if u.path == "/mon.sse":
            return self.do_mon_sse(qs)

        self.send_response(404)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Not found")

    def do_index(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(PAGE_HTML)

    def do_mon(self):
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(collect_mon()).encode("utf8"))

    def do_mon_sse(self, qs):
        # https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events
        # curl -N http:/localhost:8000/mon.sse
        update_rate = int("".join(qs.get("update-rate", ["300"]))) / 1000

        self.send_response(200)
        self.send_header("X-Accel-Buffering", "no");
        self.send_header("Content-Type", "text/event-stream");
        self.send_header("Cache-Control", "no-cache");
        self.end_headers()
        while True:
            try:
                self.wfile.write(b"data: ")
                self.wfile.write(json.dumps(collect_mon()).encode("utf8"))
                self.wfile.write(b"\n\n")
                self.wfile.flush()
            except BrokenPipeError:
                return
            time.sleep(update_rate)

def main():
    parser = argparse.ArgumentParser(description='Start hwwwmon')
    parser.add_argument(
        '--listen', '-l',
        type=str,
        default='0.0.0.0',
        help='IP address to listen on (default: 0.0.0.0)'
    )
    parser.add_argument(
        '--port', '-p',
        type=int,
        default=8484,
        help='Port number to listen on (default: 8484)'
    )
    args = parser.parse_args()

    init_mon()
    print(f"Listening on {args.listen}:{args.port}")
    httpd = http.server.HTTPServer((args.listen, args.port), HwmRequestHandler)
    httpd.serve_forever()

PAGE_HTML = Template("""
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
    <meta charset="UTF-8" />
    <title>hwwwmon: ${hostname}</title>
    <style>
body {
    font-family: sans;
}
section {
    margin: 1rem 0;
}
    </style>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"
            integrity="sha512-ZwR1/gSZM3ai6vCdI+LVF1zSq/5HznD3ZSTk7kajkaj4D292NLuduDCO1c/NT8Id+jE58KYLKT7hXnbtryGmMg=="
            crossorigin="anonymous"
            referrerpolicy="no-referrer"></script>
  </head>
  <body>
    <h1>hwwwmon: ${hostname}</h1>
    <form onsubmit="return false;">
      <button onclick="monPause()">⏸️</button>
      <button onclick="monStart()">▶️</button>
      <button onclick="monStop()">⏹️</button>
      <label>Update every <input type="number" id="update-rate" value="300" onchange="monStop();monStart()" />ms</label>
      <label>Show <input type="number" id="max-points" value="200" min="1" />data points</label>
    </form>
    <div id="chart-container"></div>
    <script>
const mon_charts={};

function updateCharts(mon_data, updateCharts, maxPoints) {
    // https://www.chartjs.org/docs/latest/charts/line.html
    return Promise.resolve().then(() => {
        // First loop: Make sure we have all elements created
        Object.keys(mon_data).forEach((mon_type) => {
            if (mon_type === "_errors") {
                // TODO: console.warn(mon_data["_errors"]);
                return;
            }
            if (!mon_charts[mon_type]) {
                document.getElementById("chart-container").insertAdjacentHTML('beforeend', `<section>
                    <canvas data-mon_type="${mon_type}"></canvas>
                </section>`);
            }
        });
    }).then(() => {
        const timeStr = (new Date()).toLocaleTimeString();

        // Now DOM is updated, create charts
        Object.keys(mon_data).forEach((mon_type) => {
            if (mon_type === "_errors") return;
            if (!mon_charts[mon_type]) {
                mon_charts[mon_type] = new Chart(document.querySelector(`#chart-container canvas[data-mon_type=${mon_type}]`), {
                    type: 'line',
                    data: { datasets: [] },
                    options: {
                        animation: false,
                        elements: {
                            line: { // https://www.chartjs.org/docs/latest/configuration/elements.html#line-configuration 
                                borderWidth: 2,
                            },
                            point: { // https://www.chartjs.org/docs/latest/configuration/elements.html#point-configuration
                                radius: 1,
                            },
                        },
                        plugins: {
                            title: {  // https://www.chartjs.org/docs/latest/configuration/title.html#title
                                display: true,
                                text: mon_type,
                            },
                        },
                    },
                });
            }
            const chart = mon_charts[mon_type];
            chart.data.labels.push(timeStr);
            while (chart.data.labels.length > maxPoints) chart.data.labels.shift();
            Object.keys(mon_data[mon_type]).forEach((mon_name) => {
                let i = 0
                for (i = 0; i < chart.data.datasets.length; i++) {
                    if (chart.data.datasets[i].label === mon_name) break;
                }
                if (i >= chart.data.datasets.length) chart.data.datasets.push({ label: mon_name, data: [] });
                chart.data.datasets[i].data.push(mon_data[mon_type][mon_name]);
                while (chart.data.datasets[i].data.length > maxPoints) chart.data.datasets[i].data.shift();
            });
            if (updateCharts) chart.update();
        });
    });
}

function monStart() {
    window.hwUpdateCharts = true;
    if (window.evtSource) return;

    const updateRate = document.getElementById("update-rate").value;
    window.evtSource = new EventSource(`/mon.sse?update-rate=${updateRate}`);
    window.evtSource.onmessage = (event) => {
        const maxPoints = parseInt(document.getElementById("max-points").value, 10);
        return updateCharts(JSON.parse(event.data), window.hwUpdateCharts, maxPoints);
    };
}

function monStop() {
    if (!window.evtSource) return;
    window.evtSource.close();
    window.evtSource = undefined;
}

function monPause() {
    window.hwUpdateCharts = !window.hwUpdateCharts;
}

window.addEventListener("DOMContentLoaded", monStart);
window.addEventListener("beforeunload", monStop);
    </script>
  </body>
</html>
""").safe_substitute(hostname = socket.gethostname()).encode("utf8")

if __name__ == '__main__':
    main()
