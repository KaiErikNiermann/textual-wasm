# Benchmarks

What a textual-wasm build costs in CPU, memory and time, measured, with each cost attributed to the layer that causes it: the browser, the Python interpreter, Textual, this project's driver and data channel, or the application.

:::{note}
The tables on this page are **generated** from `bench/results/latest.json` by `just bench-report`, and the gates fail when the committed copy drifts from the results. Every number here was taken by `just bench` on the machine described below. Absolute numbers will differ on yours; the ratios between layers, engines and runtimes are the part that carries over.
:::

## Summary

**In these runs, an idle app cost nothing measurable.** A static textual-wasm app sitting in a Chromium tab used 0.00% of a core, the same as `about:blank`, in both the main-thread and the worker build, and wrote nothing to its terminal. In Firefox the empty browser itself idled at about 0.8% and the app read within a few tenths of that, which is about the resolution of the measurement. The common case above the floor is a focused input: Textual blinks its cursor twice a second, and each blink is a redraw - measured at about 1% of a core in Chromium and 2% in Firefox, against 0.2% for the same app on a native terminal.

**Most of the measured memory is the interpreter.** Of what the benchmark app added to an empty browser tab - 160-175 MiB in Chromium, about 205 MiB in Firefox - Pyodide itself is 106-168 MiB, importing Textual 23-58 MiB, and the app 10-22 MiB. The interpreter's WebAssembly memory was 43 MiB and did not grow in any of the workloads here.

**On this machine, boot took about three seconds on a first visit and two when cached**, most of it booting the interpreter (0.8-1.2 s) and installing packages (0.4-1 s, depending on the cache). Starting the benchmark app itself - importing it, composing it and drawing the first frame under Pyodide - took about 0.6 s, in both builds and both engines; a larger app will take longer.

**In these runs, most of a message's cost was not the data channel.** A round trip took 0.1 ms in Chromium (Firefox's clock does not resolve it on this page), a megabyte 3-5 ms, and the page sent far faster than the app could receive - 200,000 messages left in 0.1-0.5 s and took 2.2-3.6 s to handle. But 10,000 messages through the channel took 115 ms in Chromium when Textual's own message pump, fed the same number from inside Python, took 111 ms. That puts the measured ceiling at Textual's message queue running under Pyodide: the channel added 4-6% on the main thread, and about 30% in a worker build, where every message also crosses `postMessage`.

**On these workloads, Pyodide ran pure Python about 1.5x slower than CPython, and Textual work 2-7x slower.** A loop that touches nothing but the interpreter ran 1.5x (Chromium) to 1.7x (Firefox) slower than natively. Textual's message pump ran 2.2x to 2.9x slower and mounting widgets 3x to 7x slower, so those workloads lost more than raw interpreter speed explains. The extra is probably in what they do that the loop does not, such as allocation and scheduling, but that was not measured separately; Firefox paid more of it than Chromium.

**No leaks observed in textual-wasm under this harness.** Over 50,000 messages the WebAssembly memory stayed flat, and so did the browser's memory in Chromium, where every JavaScript realm can be collected before a reading. The page heap grew by 3-7 KiB per 5,000 messages - about a byte a message, too little for ten rounds to tell from settling - and the nine or so Python objects added per round look like Textual's bounded render caches filling: run natively for 400,000 messages, the count stayed flat. Firefox offers no way to force a collection, so its memory readings cannot rule a slow leak in or out. Mounting and removing widgets natively did grow, towards a bound of 1,024 entries, because a cache in Textual keeps removed widgets' render caches alive ([Textualize/textual#6665](https://github.com/Textualize/textual/issues/6665)). That is Textual's, and it happens on a terminal too.

## Results

The layers the tables are split by (`blank`, `pyodide`, `textual`, `tick`, `app`, `input`) and how each number is read are described in [How it is measured](#how-it-is-measured) below.

```{include} benchmark-results.md
```

## How it is measured

### Attribution: one layer at a time

A number measured against the full page says what the page costs, and nothing about why. So every idle and memory measurement is taken on a ladder of pages, each one layer above the last, all served from the same build and brought up by the build's own `boot.mjs`:

| Layer | What is running |
|---|---|
| `blank` | `about:blank` in the same browser. The engine's own cost. |
| `pyodide` | The interpreter booted, running nothing. |
| `textual` | The build's requirements installed and Textual imported, still running nothing. |
| `tick` | The above plus one asyncio task waking every 50ms: the escape-sequence timer the driver kept running before it was made input-only, and nothing else of the driver. |
| `app` | The benchmark app: a static screen, running, untouched. |
| `input` | An app with a focused, blinking input: the common case above the floor. |

The difference between two adjacent rows is what the added layer costs. Each layer runs in both builds - the interpreter on the page's main thread, and in a Web Worker - and in Chromium and Firefox.

A second ladder runs sideways, from the browser to a native terminal. The same apps run on CPython in a real pseudo-terminal through Textual's own platform driver (`textual_wasm.reference`, the same reference the render check uses), and the same workloads run natively under `App.run_test`. A browser number next to its native counterpart says what the browser runtime adds.

### What is read, and how

- **CPU** is the user and system time of the whole browser process tree - the browser, its renderer, GPU and utility processes, and any worker - read from the operating system over a 10-second window while the page is untouched. It is reported as a percentage of one core. The page's own APIs see one thread; the process tree sees everything the browser did.
- **Main-thread breakdown** comes from Chromium's own accounting through the DevTools protocol: how much of the main thread's time went to tasks and to script. It sees the page's main thread only, so in a worker build the interpreter's time is in the CPU column and not here.
- **Redraws** are counted rather than timed: the page counts every write the app makes to the terminal (`textualWasm.output()`). An idle app that redraws for no reason shows up as a number that is not zero.
- **Memory** is the proportional set size (PSS) of the browser's process tree: every shared page divided between the processes that share it, so the total is what the browser really holds rather than six copies of the same libraries. Beside it are the page's JavaScript heap after a forced collection (Chromium), the interpreter's WebAssembly memory, and the number of Python objects the cycle collector tracks.
- **Boot time** is split at `performance.mark`s the page leaves as each step starts, all on the page's own clock in both builds.
- **The data channel** is timed inside the page, never from the automation driver, whose own round trip would swamp a 0.1ms crossing.
- **Leaks** are found by repeating a workload in rounds and reading memory after each, after a full collection of Python, the page and - in Chromium - the worker. Growth that continues into the second half of the rounds is a leak; the counter it shows in says whose.

Each case runs in a fresh browser, one at a time, so no measurement carries another's leftovers and no two browsers compete for the machine. Durations are medians over repeats.

### Whose cost: the controls

Three workloads run inside Python, timed from inside Python, identically in every runtime:

- a pure arithmetic loop, which touches nothing but the interpreter;
- a flood of messages an app posts to itself, which is Textual's message pump with no channel involved;
- mounting and removing widgets, which is Textual's DOM and compositor.

The loop's native-to-browser ratio is the cost of running CPython as WebAssembly. A workload with the same ratio is slow because of the interpreter, not because of anything built on it. The data channel's throughput is compared the same way, against the bridge fed directly under CPython, with the page, the transport and the browser removed.

## Reproducing

```bash
just install && just install-browsers chromium firefox
just bench           # about an hour; resumes where it stopped if interrupted
just bench-report    # regenerate the tables on this page
```

`just bench-smoke` runs every case at toy sizes in a few minutes, to check the harness works. Chromium and Firefox are the default engines; `just bench --engine webkit` adds Playwright's WebKit where it is installed, and `--only NAME` reruns the cases whose name contains `NAME`. The harness itself is in [`bench/`](https://github.com/KaiErikNiermann/textual-wasm/tree/main/bench): the apps it measures, the scenario runner and the baseline pages. A first visit fetches Pyodide and the wheels from jsDelivr, so the first-visit boot rows depend on the network; everything else is local.

The benchmark also runs weekly on a GitHub runner (`bench.yml`), with the tables in the job summary. Those numbers are noisier than a quiet machine's and are not the ones on this page. What runs on every push is the part that cannot be noisy: `tests/test_bench.py` asserts the counted results - an idle app writes nothing, no message is dropped, the page is published only once the app has drawn - in a real browser, in both builds.
