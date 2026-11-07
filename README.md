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

### Your Nexus API key
1. Go to <https://www.nexusmods.com/settings/api-keys> and copy the **Personal API Key** at the bottom of the page.
2. Paste it into the tool and press **Log in**. It should say *Logged in as … (Premium)*.

The key is stored encrypted with your Windows login (DPAPI) in `%APPDATA%\SkyrimDownloaded\settings.json`. You can instead set the `NEXUS_API_KEY` environment variable.

## Using the window

1. **Nexus account:** paste your key and log in.
2. **Mod manager:** pick MO2 or Vortex and one of the two modes.
   - **MO2:** choose your instance folder.
     - Global instances live in `%LOCALAPPDATA%\ModOrganizer\<name>`; the drop-down lists the ones it finds.
     - For a portable install, choose the folder `ModOrganizer.exe` is in.
     - The downloads folder is read from the instance's `ModOrganizer.ini`.
     - For "Mod manager downloads", also point it at `ModOrganizer.exe`.
   - **Vortex:**
     - Leave the paths blank if Vortex is installed in the usual place and uses its default downloads folder (`%APPDATA%\Vortex\downloads\skyrimse`).
     - If you moved the downloads folder (Vortex → Settings → Downloads), choose it here. Either the main folder or its `skyrimse` folder works.
   - "Downloads go to: …" shows where files will land.
3. **Mod list:** open a `.txt` file, or type or paste links into the box. Then press **Look up mods**.
4. **Choose options:** for every mod with more than one file, a window steps you through them one at a time. Tick the files you want, or choose **Leave this mod out**. You can change any choice later in the list.
   - Tick or untick a file by clicking its box or double-clicking the file.
   - Select a file to read its description.
   - Choose **Open mod page** to check the mod's page on Nexus.
5. **Start downloads.** For "Mod manager downloads", open MO2 or Vortex on your Skyrim setup first. If you stop part way, start again later and it carries on where it left off.

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
python -m skyrimdl detect
```

```bash
python -m skyrimdl run my-mods.txt --manager mo2 --mo2-instance "Skyrim AE" --mode handoff --mo2-exe "C:\Modding\MO2\ModOrganizer.exe"
```

```bash
python -m skyrimdl run my-mods.txt --manager vortex --mode direct
```

`login` saves your API key and `detect` shows the MO2 instances and Vortex folders it finds.

Useful flags for `run`:

| Flag | What it does |
|---|---|
| `--dry-run` | Looks everything up and shows the plan without downloading |
| `--yes` | Never asks: takes the primary file wherever a mod has options |
| `--fresh` | Ignores the choices saved last time |
| `--include-old` | Also offers old versions |
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
  config.py      settings, DPAPI-protected API key, saved choices
  cli.py, gui.py command line and Tk window
```
