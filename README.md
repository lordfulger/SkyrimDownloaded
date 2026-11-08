# SkyrimDownloaded

Give it a list of Nexus Mods links and it gets every mod into **Mod Organizer 2** or **Vortex** for Skyrim Special/Anniversary Edition, using your own Nexus account (Premium).

It works like a Vortex Collection, but the "collection" is your own list of links. When a mod has more than one file to choose from (1K or 2K textures, main file plus optional patches, and so on), it shows you those options, just as the mod's Files tab would. You tick what you want, and it remembers your choices for next time.

![Flow](https://img.shields.io/badge/list_of_links-%E2%86%92_choose_options_%E2%86%92_MO2_%2F_Vortex-6b4fbb)

## What it does

- **Reads any list of links.** Nexus page links, links to a specific file (`?tab=files&file_id=…`), `nxm://` links, or bare mod numbers all work. You can paste a whole guide (a Reddit post or a web page) and every Nexus link in it is picked up.
- **Shows the download options.** If a mod has several current files, you choose which to get. Each file's description is shown so you can tell "Performance 1K" from "2K" without opening the site.
- **Remembers your answers.** They're saved beside your list (`<list>.choices.json`), so running the list again doesn't ask the same questions.
- **Checks requirements.** If a mod in your list needs another mod that isn't in it (SKSE, Address Library…), it tells you and offers to add it. Requirements that aren't on Nexus are listed so you can get them yourself.
- **Skips what you already have.** Files already in the mod manager's downloads folder aren't downloaded again.
- **Handles problems.** Removed mods, deleted files, and files replaced by a newer version are flagged instead of stopping the run. Downloads resume after a dropped connection. The Nexus API limit is respected.

## Two ways to get files into your mod manager

| | **Mod manager downloads** (recommended) | **Download here, into its downloads folder** |
|---|---|---|
| Who downloads | MO2 or Vortex, with your Nexus login. The tool sends it an `nxm://` link for each file you chose, the same as clicking "Mod manager download" on the site. | This tool, straight from the Nexus CDN (Premium speed, 3 files at a time). |
| Mod Organizer 2 | Files appear in MO2's **Downloads** tab with full Nexus info. Install them there (installer/FOMOD options run in MO2). | Archives go into the instance's downloads folder **with the `.meta` file MO2 uses**, so MO2 shows them with their Nexus name, version and mod ID. Install from the **Downloads** tab. |
| Vortex | `Vortex.exe --install nxm://…`: Vortex downloads **and installs** each mod, showing its installer options (FOMOD) when it has them. Untick "Install after download" to only download. | Archives go into Vortex's downloads folder for Skyrim SE, then `Vortex.exe --install-archive` installs each one. |

Both need **Premium**. Nexus only gives tools download links for Premium accounts.

## Setup (Windows)

### Option A: the .exe (no Python needed)
Download `SkyrimDownloaded.exe` from the latest run of the **Build** workflow (the repo's *Actions* tab → *Build* → *Artifacts*) and run it.

### Option B: run from source
1. Install Python 3.10 or newer from [python.org](https://www.python.org/downloads/windows/). The installer includes Tk, which the window needs.
2. Download this repo (green **Code** button → *Download ZIP*) and unzip it.
3. Double-click **`SkyrimDownloaded.bat`**.

No extra packages are needed: it uses only Python's standard library.

### Logging in to Nexus
1. Press **Log in with Nexus**. Your browser opens Nexus's API key page (log in there if asked).
2. Click **Copy** next to your **Personal API Key**, or select it and press Ctrl+C.

SkyrimDownloaded spots the key on your clipboard, logs in, and clears the clipboard. It should then say *Logged in as … (Premium)*. You only do this once.

You can also paste the key into the box and press **Use key**. **Log out** forgets the key.

The key is stored encrypted with your Windows login (DPAPI) in `%APPDATA%\SkyrimDownloaded\settings.json`. You can instead set the `NEXUS_API_KEY` environment variable.

**Why not a sign-in button like MO2's?** That kind of sign-in needs an application ID that Nexus issues to each program, and SkyrimDownloaded doesn't have one yet. Borrowing MO2's or Vortex's would break Nexus's API rules.

### Dark mode
Use **Theme** at the top right: **System** follows Windows' light/dark app setting, or choose **Light** or **Dark**. Dark mode also darkens the title bar on Windows 10 and 11.

## Using the window

1. **Nexus account:** press **Log in with Nexus** (see above).
2. **Mod manager:** pick MO2 or Vortex and one of the two modes, then press **🔍 Find automatically**.
   - It searches this PC for Mod Organizer 2 and Vortex and fills in the folders. If you have more than one Skyrim setup, it asks which one to use.
   - A quick version of the search also runs every time the program starts, filling in anything left blank.
   - "Downloads go to: …" shows where files will land. Use **Browse…** if the search picked the wrong place or found nothing.

   **What the MO2 instance folder is:** an *instance* is one complete MO2 setup: one game, with its own mods, profiles, downloads and settings. Its folder is the one with `ModOrganizer.ini` in it. That file says which game the instance is for and where its `mods`, `profiles` and `downloads` folders are. The tool reads it to know where downloads go, and to check the instance is for Skyrim SE/AE.
   - **Global instances** (made with MO2's "Create a new instance") live in `%LOCALAPPDATA%\ModOrganizer\<name>`.
   - **Portable instances** (and every Wabbajack list) are the folder `ModOrganizer.exe` itself is in.
   - The instance shown in MO2's title bar is the one to pick.

   **How the search works:**
   - It checks which program opens `nxm://` links and the installed-programs list in the registry.
   - It looks at MO2's global instances and Vortex's own settings, which include a moved downloads folder.
   - It searches your drives a few folders deep for `ModOrganizer.exe`, `Vortex.exe` and the marker file Vortex keeps in its downloads folder. This step stops after a minute.
3. **Your Skyrim:** pick your game version, or press **Detect** to read it from your `SkyrimSE.exe` (see below).
4. **Mod list:** open a `.txt` file, or type or paste links into the box. Then press **Look up mods**.
5. **Choose options:** for every mod with more than one file, a window steps you through them one at a time. Tick the files you want.
   - **Skip for now** puts a mod off; it comes back after all the others. If you press **Done** while some are still skipped, they stay highlighted in the list.
   - **Leave this mod out** drops it from this download.
   - The wheel, middle-click scrolling and Page Up/Down all scroll the list of files.
   - In the main list, tick or untick a file by clicking its box or double-clicking it. **Choose options…** opens the window again.
   - **Click a mod** to see its Nexus page in the panel on the right: author, version, last update, endorsements, downloads, summary and full description. The panel also shows its requirements (in your list or not) and its links with your other mods. Click a file to see that file's details.
6. **Compatibility check:** when you finish choosing options, the tool checks how the mods in your list relate to each other (see below). It then offers to **review** the mods involved, with suggested patches already ticked. **Check compatibility** runs the check again any time.
7. **Start downloads.** For "Mod manager downloads", open MO2 or Vortex on your Skyrim setup first. If you stop part way, start again later and it carries on where it left off.

## Picking files for your Skyrim version

Many mods offer separate files for different versions of the game. SSE Engine Fixes, for example, has one for 1.5.97 and one for 1.6.1170, and some mods have a VR build. Set **Your Skyrim** and files for other versions are left out. When only one file is left, it's picked without asking.

- **Detect** reads the version from `SkyrimSE.exe`. It uses your MO2 instance's game folder if it has one, otherwise your Steam or GOG install. With a blank version, Detect runs on its own at start-up.
- **Which Skyrim versions match:** a file made for any version in the same group as yours counts as yours.

  | Group | Versions |
  |---|---|
  | SE | 1.5.97 and other 1.5 versions |
  | early AE | 1.6.353 and before |
  | AE 640 | 1.6.640, including GOG 1.6.659 |
  | AE 1130+ | 1.6.1130, 1.6.1170 and later |
  | VR | 1.4.15 |

  Patches inside a group generally work with each other's files, so a plugin made for 1.6.1130 still counts as yours on 1.6.1170. A file made for a **newer** build than yours is left out, even within your group. For example, on 1.6.1130 a file "for 1.6.1179" is hidden.
- **What it reads:** Nexus doesn't record which game version a file is for, so the tool reads the file's **name**:
  - version numbers (`1.5.97`, `1.6.640`, `AE 1170`, `1.6.1130+`, `640 and older`)
  - the words *AE*, *pre-AE* and *VR*
  - store names (*GOG*, *Game Pass*)

  Files marked *SE/AE* or *all versions* are kept for everyone. A version only mentioned in a file's **description** is shown as a note and doesn't hide the file. The exception is a description that says plainly the file is *for*, *requires* or *needs* a version newer than yours, e.g. "Requires 1.6.1170"; that file is hidden.
- **Store:** GOG and Game Pass builds have their own files, so set **from** to where your game came from.
- **Seeing what was left out:** tick **Show files for other game versions**. Each file says what it's for, e.g. "for SE 1.5.97 (not your version)". If every file of a mod looks like it's for another version, nothing is hidden and you're asked to choose.
- **Changing the version later:** files are picked again right away. Mods where you'd already picked a file for the old version are highlighted for you to check.
- **Command line:** `--game-version 1.6.1170` (or `any`) and `--store gog`. `detect` shows the Skyrim installs it finds.

## Picking up where you left off

Your work is saved as you go and when you close the app. Next time it opens, everything is back where you left it:
- the mod list, including edits you haven't saved to a file
- every looked-up mod, with its files and the options you picked
- mods still waiting for a choice or skipped for later
- the compatibility results
- the view settings and the window size

**Save progress** saves straight away if you want to be sure. **Start over** clears everything for a new list; a list you saved to a file stays on disk.

The saved work is in `%APPDATA%\SkyrimDownloaded\session.json`. It holds what Nexus said when you last looked the mods up, so press **Look up mods** to refresh it if a while has passed. Your choices are kept.

## Compatibility check

The check catches things a collection's author would normally have sorted out. For each mod in your list it looks at:

| Where | What it finds |
|---|---|
| The mod's **requirements** on Nexus | Mods that rely on another mod in your list ("Pretty Textures needs SkyUI") |
| The mod's **files** | Patch files for another mod in your list, e.g. a "USSEP patch" file when USSEP is in your list. These are suggested and get ticked when you review. |
| The mod's **page description** | "incompatible with X" or "don't use with X" (possible conflict), "requires X", "works with X", or a mention of X, where X is another mod in your list |

- **How mods are recognised:** by name, short forms such as "USSEP" for the Unofficial Skyrim Special Edition Patch, and links to their Nexus page.
- **Review:** walks you through just the mods involved. Warnings ("may conflict with …", "needs …") are shown at the top, and suggested patches are marked with ★.
- **Read it as a checklist, not a verdict.** Page text is read automatically, so a conflict is flagged as "possible" and is worth checking on the mod's page.
- **Missing requirements** (mods your list needs but doesn't have) are still offered when you press **Look up mods**.
- **Command line:** the report is printed after the options, and it offers to tick the suggested patches. `--no-compat` turns it off.

## Scrolling and resizing

- **Middle-click scrolling** works in the mod list, the file list, the info panel and the options window, like a web browser:
  - Click the wheel once, then move the mouse up or down. The further from where you clicked, the faster it scrolls. Click again, or press Esc, to stop.
  - Or hold the wheel and drag; it stops when you let go.
- **Drag the bar** between the mod list (3) and the files (4) to give either one more room. The bar between the file list and the info panel works the same way.
- The mod list has scrollbars both ways, for long lists and long lines.

## The list file

One link per line. Lines without a link are ignored, and anything after ` #` is a note shown next to the mod.

```text
# ---- Essentials ----
https://www.nexusmods.com/skyrimspecialedition/mods/30379     # SKSE64
https://www.nexusmods.com/skyrimspecialedition/mods/32444     # Address Library
https://www.nexusmods.com/skyrimspecialedition/mods/12604     # SkyUI

# a link to one exact file: no question asked
https://www.nexusmods.com/skyrimspecialedition/mods/266?tab=files&file_id=123456

# bare mod numbers work too (Skyrim SE/AE)
17230
```

To answer a mod's options ahead of time, add `|` and a choice after the link:

| After the link | Gets you |
|---|---|
| *(nothing)* | The only file, or **asks** when there's more than one |
| `\| ask` | Always shows the options, even for a single file |
| `\| primary` | Just the main file Nexus marks as primary. Never asks. |
| `\| main` | Every file in the *Main files* section |
| `\| all` | Every main, update, optional and misc file |
| `\| match=2K` | Files whose name contains "2K". Use it more than once to match several (`match=2K, match=Patch`). Spaces are fine (`match=Pretty Textures 2K`); quote text that contains a choice word, e.g. `match="Main Menu"`. |
| `\| file=123456,123457` | Exactly those file IDs (the number in a file's download link) |
| `\| skip` | Leaves the mod out but keeps it in the list |

[`example-modlist.txt`](example-modlist.txt) is a short list to try.

## Command line

The same thing without the window, handy for big lists:

```bash
python -m skyrimdl login
```

```bash
python -m skyrimdl detect --deep --save
```

```bash
python -m skyrimdl run my-mods.txt --manager mo2 --mo2-instance "Skyrim AE" --mode handoff --mo2-exe "C:\Modding\MO2\ModOrganizer.exe"
```

```bash
python -m skyrimdl run my-mods.txt --manager vortex --mode direct
```

`login` saves your API key. `detect --deep --save` searches the PC for MO2 and Vortex and remembers what it finds. Without `--deep`, it only does the quick search. `run` also fills in any blank paths by itself.

Useful flags for `run`:

| Flag | What it does |
|---|---|
| `--dry-run` | Looks everything up and shows the plan without downloading |
| `--yes` | Never asks: takes the primary file wherever a mod has options |
| `--fresh` | Ignores the choices saved last time |
| `--include-old` | Also offers old versions |
| `--game-version 1.6.1170` / `--store gog` | Your game, so files for other versions are left out (`any` turns this off) |
| `--show-other-versions` | Also offers files that look like they're for other game versions |
| `--no-compat` | Skips the compatibility check |
| `--add-requirements` / `--no-requirements` | Adds missing requirements without asking, or skips the requirements check |
| `--no-install` | Vortex: only download, don't install |
| `--downloads <folder>` | Uses a different downloads folder |
| `--redownload` | Downloads files again even if you already have them |
| `--parallel N` | Sets how many files download at once in direct mode |

Run `python -m skyrimdl run --help` for everything.

## Good to know

- **AE and SE are the same on Nexus.** Both use the `skyrimspecialedition` pages. Links for other games (e.g. Oldrim's `skyrim`) are flagged, because your mod manager will refuse them for an SE instance.
- **Install order:** MO2 doesn't sort your load order. Use LOOT, or the order your guide gives. Vortex sorts plugins itself.
- **API limits:** Nexus allows a personal key roughly 2,500 requests a day (then 100 an hour). Looking up a mod costs about 3 requests, and a direct download 1 more. Once the daily allowance runs out, the hourly limit is very low. The remaining count is shown at the end of a command-line run.
- **Removed or replaced files:** if a linked file was deleted (often because a newer version replaced it), the tool picks the current primary file and asks you to confirm.
- **This uses the official Nexus API with your own key,** the same way MO2 and Vortex do. It downloads only what you could download yourself, and every download counts toward the mod author's download stats.

## For developers

```bash
python -m unittest discover -s tests -t .
```

The tests run against a small fake Nexus server (`tests/fake_nexus.py`), so they need no key or network.

```text
skyrimdl/
  links.py       read the list (links, nxm, ids, | choices)
  nexus.py       Nexus API v1 client (+ v2 GraphQL for requirements)
  selection.py   file options and which ones to pick
  engine.py      look up a list, find missing requirements, run downloads / handoffs
  downloader.py  resumable download with retries
  managers/      mo2.py (.meta files, ModOrganizer.ini), vortex.py (Vortex CLI)
  finder.py      find MO2 instances, ModOrganizer.exe, Vortex.exe and its downloads folder
  config.py      settings, DPAPI-protected API key, saved choices
  theme.py       light / dark / follow-Windows looks for the window
  gameversion.py which game version a file is for; find Skyrim and read SkyrimSE.exe's version
  compat.py      requirements, patches and conflicts between the mods in a list
  text.py        Nexus BBCode descriptions to plain text
  scrolling.py   middle-click and mouse-wheel scrolling
  session.py     save and restore the work in progress
  cli.py, gui.py command line and Tk window
```
