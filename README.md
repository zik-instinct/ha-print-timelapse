# Print Timelapse Archive

A Home Assistant custom integration that records a timelapse of every 3D print and keeps a searchable archive you can watch inside a printer-dashboard card or in a sidebar panel, on desktop or mobile.

![Print Timelapse Archive](brand/icon.png)

## What it does

- Watches a **printer status sensor** (PrusaLink, OctoPrint, Moonraker, anything with a status sensor) and starts capturing whenever the printer reports a printing state.
- Captures frames from **any existing camera entity** at a configurable interval.
- When the print ends, assembles **720p and 1080p videos** with ffmpeg and archives them with a preview frame.
- Adds a **Timelapses sidebar panel**: browse every saved print with poster, file name, capture span, gap details and one-tap playback. Search by job or file name.
- Adds an **archive sensor** (saved-print count, free space, last error) and a **capture sensor** (idle / capturing / assembling) for your own dashboards and automations.
- Everything stays **local and authenticated**. Videos are served through Home Assistant's signed media paths; nothing is published or sent anywhere.

Integration setup and capture settings are configured from the Home Assistant UI. Embedding the card currently uses a short card configuration, shown below.

## Requirements

- Home Assistant **2026.9 or newer** (2026.9 is the minimum because the integration is built on the `probatio` validation library that replaced `voluptuous` in 2026.9). Runtime-tested end to end on Home Assistant Core **2026.10.2** only.
- `ffmpeg` available on the system. This is already true for Home Assistant OS, Supervised and the official container image.
- A camera entity pointed at the print bed.
- A sensor entity reporting the printer state, plus the states that mean "printing" (default: `printing`).

## Installation with HACS

1. In HACS, open the menu and choose **Custom repositories**.
2. Add `https://github.com/zik-instinct/ha-print-timelapse` with type **Integration**.
3. Install **Print Timelapse Archive** and restart Home Assistant.
4. Go to **Settings → Devices & services → Add integration** and search for **Print Timelapse Archive**.
5. Pick the camera and the printer status sensor, and adjust the states/interval if needed. A **Timelapses** entry appears in the sidebar.

## Add it to a printer dashboard

The same browser is available as a card, so it can live inside an existing printer dashboard instead of the sidebar. The integration registers its JavaScript resource automatically when your dashboards are in storage mode (the default). Then add a card:

```yaml
type: custom:print-timelapse-card
```

If you manage dashboard resources in YAML, add `/print_timelapse_static/print-timelapse-panel.js` as a module resource yourself.

## Configuration

| Setting | Meaning | Default |
| --- | --- | --- |
| Camera | Existing camera entity watching the bed. A test snapshot is taken during setup. | required |
| Printer status sensor | Entity whose state says whether a print is running | required |
| States that mean printing | Comma-separated, e.g. `printing, busy` | `printing` |
| Capture interval | Seconds between frames while printing | 60 |
| File name attribute | Optional status-sensor attribute with the G-code/model name | empty |
| Video frame rate | fps of the assembled videos | 30 |
| Free space reserve | Archiving stops before the disk drops below this | 2 GB |
| Keep frames | Keep every JPEG after archiving instead of only the videos and preview | off |

All settings can be changed later from the integration's **Configure** button.

## How it works

- Frames land in a rolling capture folder while the status sensor reports a printing state. When the state leaves that set, the job is finalized.
- ffmpeg assembles `f_*.jpg` frames into `timelapse_720p.mp4` and `timelapse_1080p.mp4`. Only after every video is closed is the job archived.
- Archiving hard-links files into Home Assistant's local media directory when possible and otherwise copies with SHA-256 verification, keeping the configured free-space reserve. **Nothing in the archive is ever deleted automatically.**
- The panel lists jobs over the WebSocket API and plays videos through Home Assistant's authenticated, signed media URLs, so only logged-in users can watch them.
- The `print_timelapse.rebuild_index` service rebuilds the archive index from saved job metadata.

If Home Assistant restarts mid-print, capture resumes with the current job; a job interrupted by a restart is finalized when the printer is no longer printing.

## Honest limitations

- Timestamps and gap counts describe **saved frames**, not verified print start/end, and a finished video is **not proof of print success**.
- This is not a failure detector and never pauses, cancels or controls the printer.
- One printer per installation for now.
- The archive lives on your Home Assistant storage. It is not an off-site backup.

## Privacy

No analytics, no external calls, no uploaded media. The repository contains no recordings, printer file names or personal configuration.

## Development

Validation runs on every push: [hassfest](https://github.com/home-assistant/actions/tree/master/hassfest) and the [HACS action](https://github.com/hacs/action). The archive logic in `archive.py` has no Home Assistant imports and is unit-tested standalone.

Runtime-tested on Home Assistant Core 2026.10.2: UI config flow, UI options flow, full capture-to-video cycle with real ffmpeg, restart recovery, authenticated media serving, panel and card rendering (desktop and mobile). Test footage in any screenshots or test fixtures is synthetic (generated frames from a local test camera, not a real printer). Compatibility claims are limited to what was actually run: any camera entity plus any status sensor with configurable printing states; no printer-brand-specific code paths exist, but only a generic camera + synthetic status sensor have been exercised.

Brand assets ship inside the integration's `brand/` folder, as required by current HACS validation. The earlier Core 2026.10.2 UI tests showed an icon placeholder before those assets were moved into the integration. Icon display with the final asset placement has not been re-tested.

## License

MIT. See [LICENSE](LICENSE).
