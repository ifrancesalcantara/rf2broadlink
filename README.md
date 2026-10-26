# rf2broadlink

**Use 433/315 MHz remotes with a Broadlink RM4 Pro without "learning" them.**

Many cheap RF remotes (lamps, sockets, doorbells, blinds…) use the same simple
24‑bit protocol (Princeton / EV1527 / PT2262). If you know the code — from a
Flipper Zero `.sub` file, from a public database like
[UberGuidoZ/Flipper](https://github.com/UberGuidoZ/Flipper), or from a decoder —
`rf2broadlink` turns it into a Broadlink packet that Home Assistant can send
directly. No learning mode, no frequency sweep, no guessing when to press the button.

```console
$ python3 rf2broadlink.py 67AE02 --te 263 --ha
b64:sgAuAQgYGAgYCAgYCBgYCBgIGAgYCAgYGAgIGBgIGAgYCAgYCBgIGAgY…

$ python3 rf2broadlink.py Power.sub --ha          # Flipper file: TE and band read from it
```

Single file, no dependencies, Python 3.9+.

## Why not just learn the remote?

Learning RF with Home Assistant (`remote.learn_command` with `command_type: rf`)
works, but in practice:

- you have to hold the button during a ~30 s frequency sweep and then press it
  again at the right moment; buttons that don't repeat when held are hard to catch;
- captures are noisy and **long** — typically ~25 frames, almost a second of
  transmission for a single press. Sending them makes the Broadlink busy and slow,
  and several presses in a row arrive glued together.

A generated packet is clean and short (6 frames ≈ 0.2 s by default) and ends with
a silence gap, so consecutive sends are received as separate presses.

## Using it in Home Assistant

A button per remote key, e.g. with a template button helper or in YAML:

```yaml
template:
  - button:
      - name: "Floor lamp – Power"
        icon: mdi:power
        press:
          - action: remote.send_command
            target:
              entity_id: remote.living_room_rm4_pro
            data:
              command: "b64:sgAuAQgYGAgYCAgYCBgYCBgI…"
```

### Several steps per tap (brightness, colour temperature…)

Some receivers only count **separate** presses: a long or glued-together
transmission counts as one. To make one tap do *n* steps, send the single-press
packet *n* times with a pause instead of making the packet longer:

```yaml
            data:
              command: "b64:…"
              num_repeats: 4
              delay_secs: 0.3
```

With the lamp this was developed on, 0.3 s between presses was reliable; one
press was a small brightness step and ~20 presses covered the full range.

## Options

| Option | Default | Meaning |
|---|---|---|
| `--te` | from `.sub`, else 350 | Pulse unit in µs. Check the `TE:` line of the `.sub` file or your decoder. |
| `--bits` | 24 | Code length. |
| `--frames` | 6 | Repetitions of the code per press. Raise it if the receiver misses presses. |
| `--gap-ms` | 120 | Silence after the last frame. |
| `--band` | 433 | 433 or 315 (the only RF bands a Broadlink RM4 Pro can transmit). |
| `--ha` | | Print with the `b64:` prefix Home Assistant expects. |
| `--decode` | | Inspect an existing Broadlink packet (band, repeat byte, pulses, duration). |

Supported `.sub` protocols: `Princeton`, `EV1527` and `RAW`.

## Finding your code

- Search [UberGuidoZ/Flipper](https://github.com/UberGuidoZ/Flipper) (`Sub-GHz/`) for your device.
- Read your remote with a Flipper Zero, an RTL-SDR (`rtl_433`) or any 433 MHz decoder.
- Already have a noisy Broadlink capture? Codes of the same remote usually share
  the first 16 bits (the address) and differ in the last 8 (the key).

## Status and limits

- Princeton/EV1527 generation is **verified on real hardware**: 12 keys of a
  FIMEI floor lamp (433.92 MHz, TE 263 µs) through a Broadlink RM4 Pro and Home
  Assistant 2026.10. The test suite checks byte-for-byte against those packets.
- `RAW` conversion is implemented and unit-tested but **not yet verified on
  hardware** — reports welcome.
- Rolling-code remotes (garage doors, cars, most alarms) can't work this way, by design.
- Other Broadlink models with RF (RM Pro, RM4 Pro variants) use the same packet
  format and should work, but only the RM4 Pro has been tested.

## Development

```console
python3 -m unittest discover -s tests -v
```

## License

MIT No Attribution (MIT-0) — use it for anything, no attribution required. See [LICENSE](LICENSE).
