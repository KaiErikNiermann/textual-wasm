# Playground

Write a Textual app in the editor and run it in your browser, with nothing to install. **Run** (or Ctrl+Enter) starts it in a fresh Python interpreter, and **Copy link** gives you a URL that opens the same program for anyone you send it to.

```{raw} html
<iframe class="demo-frame" data-size="tall" src="playground/" title="The Textual playground: an editor and a running app" allow="clipboard-write" loading="lazy"></iframe>
```

:::{note}
The first run downloads a CPython interpreter (~10 MB, then cached by your browser), so it takes a few seconds. Later runs start from the cache.
:::

## Writing a program

Write an ordinary Textual app. The usual ending works unchanged:

```python
if __name__ == "__main__":
    MyApp().run()
```

The playground runs the program as `__main__`, catches the `run()` call, and starts that app in the browser. A program that never calls `run()` works too: the playground starts the last `App` instance it defines, or else the last `App` subclass.

Put styles in the class's `CSS` string. The program is a single file, so `CSS_PATH` has nothing to point at. The **Start from** picker has three programs to begin from. Picking one replaces the editor's contents, and Ctrl+Z brings yours back.

If the program has no app, fails to parse or raises before it starts, the terminal shows the traceback in place of the app.

## Sharing

The program is stored in the URL itself: the address bar is updated as you type, and **Copy link** copies it. There is no server and no account, and nothing is saved anywhere except in the link and in your browser's copy of your last draft.

The link looks like `…/playground/#v1.fVNNb9sw…`. After `v1.` comes the source, compressed with raw DEFLATE and base64url-encoded. It sits in the URL fragment (after the `#`), which browsers never send to the server, so a shared program stays out of every access log. Compression keeps links short: the counter starter is about 750 characters. Past about 8,000 characters the page warns you, because some chat apps cut long links short.

## Limits

- **Only what the build installs can be imported**: Textual, Rich, their dependencies and Pyodide's standard library. There is no way to add a package from inside the playground yet. {doc}`library-support` lists add-ons that work in a real build with `-r`.
- **Everything in {doc}`limitations` applies**, because this is the same runtime as every other build. There are no threads, so `@work(thread=True)` fails. Blocking calls freeze the tab.
- **The app runs in a sandboxed frame.** A link can hold anyone's code, and Python in Pyodide can call JavaScript, so the frame gets an opaque origin: it cannot read this site's storage or cookies, or anything another site on the same host keeps. Code that uses `js` still works, but only inside that frame.

The source is in [`playground/`](https://github.com/KaiErikNiermann/textual-wasm/tree/main/playground). The runner is an ordinary `textual-wasm build` whose app reads its program from the frame's URL, so nothing in the runtime is special-cased for it.
