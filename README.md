# SkyrimDownloaded

<p align="center"><img src="assets/logo.png" alt="SkyrimDownloaded" width="480"></p>

Give it a list of Nexus Mods links and it gets every mod into **Mod Organizer 2** or **Vortex** for Skyrim Special/Anniversary Edition, using your own Nexus account (Premium).

It works like a Vortex Collection, but the "collection" is your own list of links. When a mod has more than one file to choose from (1K or 2K textures, main file plus optional patches, and so on), it shows you those options, just as the mod's Files tab would. You tick what you want, and it remembers your choices for next time.

![Flow](https://img.shields.io/badge/list_of_links-%E2%86%92_choose_options_%E2%86%92_MO2_%2F_Vortex-6b4fbb)

## What it does

- **Reads any list of links.** Nexus page links, links to a specific file (`?tab=files&file_id=…`), `nxm://` links, or bare mod numbers all work. You can paste a whole guide (a Reddit post or a web page) and every Nexus link in it is picked up.
- **Shows the download options.** If a mod has several current files, you choose which to get. Each file's description is shown so you can tell "Performance 1K" from "2K" without opening the site.
- **Remembers your answers.** They're saved beside your list (`<list>.choices.json`), so running the list again doesn't ask the same questions.
- **Checks requirements.** If a mod in your list needs another mod that isn't in it (SKSE, Address Library…), it shows a link to that mod's Nexus page, ready to add with one click. Requirements that aren't on Nexus, and DLC or Creations, are listed so you can get them yourself.
  - The links appear after **Look up mods**, at the top of each mod's options window ("Needs"), and in the info panel.
  - **Add to list** adds the mod, and it's looked up straight away.
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
Download `SkyrimDownloaded.exe` from the [latest release](https://github.com/lordfulger/SkyrimDownloaded/releases/latest) and run it.

Windows may say *"Windows protected your PC"* the first time. Click **More info**, then **Run anyway**: the app isn't code-signed yet (see [SIGNING.md](SIGNING.md)).

### Option B: run from source
1. Install Python 3.10 or newer from [python.org](https://www.python.org/downloads/windows/). The installer includes Tk, which the window needs.
2. Download this repo (green **Code** button → *Download ZIP*) and unzip it.
3. Double-click **`SkyrimDownloaded.bat`**.

No extra packages are needed: it uses only Python's standard library. To see mod pictures when running from source, also install Pillow (`py -m pip install pillow`); the `.exe` already includes it.

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
   - **Find** above the box (or **Ctrl+F** while you're in the list) marks every match in the list. **Enter** or **▼** goes to the next one, **Shift+Enter** or **▲** to the one before, **Esc** clears it.
5. **Choose options:** for every mod with more than one file, a window steps you through them one at a time. Tick the files you want.
   - **Next** chooses the ticked files and moves on. **Back** goes to the previous mod without choosing anything for the one you're on, unless you changed its ticks.
   - **Done** pauses. The mod on screen isn't chosen for you unless you changed its ticks. Press **Choose options…** later and it carries on at the first mod still waiting, with **Back** for the ones before it. Your place is kept even if you close the app.
   - **Skip for now** puts a mod off; it comes back after all the others. Mods still skipped or waiting stay highlighted in the list.
   - **Leave this mod out** drops it from this download.
   - The wheel, middle-click scrolling and Page Up/Down all scroll the list of files. **Ctrl+F** finds a file in the list (**Enter** for the next match).
   - Warnings at the top ("needs …", "may conflict with …") link to that mod's Nexus page: click the name. After "needs …" it says whether that mod will be downloaded: **✓ in your list**, **Add to list** if it isn't in your list, or **Include it** if it's in your list but left out.
   - In the main list, tick or untick a file by clicking its box or double-clicking it. **Choose options…** opens the window again.
   - **Click a mod** to see its Nexus page in the panel on the right: its picture, author, version, last update, endorsements, downloads, summary and full description. The panel also shows its requirements (in your list or not) and its links with your other mods. Click a file to see that file's details.
   - **Search** (or **Ctrl+F**) filters the mods by name, author, your note or file name. **Enter** selects the first mod shown, **Esc** clears it.
   - **Bulk actions ▾** applies one change to every mod shown (all of them, or just the ones matching the search):
     - tick all suggested patches
     - leave out every optional file
     - untick files for other game versions
     - keep only the main files
     - expand or collapse everything
6. **Check compatibility** (optional, whenever you like) shows how the mods in your list relate to each other (see below). It then offers to **review** the mods involved, with suggested patches already ticked.
7. **Start downloads.** For "Mod manager downloads", open MO2 or Vortex on your Skyrim setup first. When downloading here, each file shows its speed and time left, and the bottom bar shows the total. If you stop part way, start again later and it carries on where it left off.
8. **Sort with LOOT** once the mods are installed, to sort the load order (see below).

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

## Installing everything in MO2: collections for MO2, from your own list

Tick **Install after download** in step 2 and press **Start downloads**. Then:

1. Each file is sent to MO2 in your list's order, and MO2 downloads it with your Nexus login. (Or SkyrimDownloaded downloads it, in "Download here" mode.)
2. Once everything has arrived, the **SkyrimDownloaded add-on** inside MO2 installs it all by itself:
   - **in your list's order**, even if MO2 finished the downloads in a different order
   - **showing the options window for mods that have installer options (FOMOD)**, so you choose those as you go
   - **skipping mods that are already installed**, and installing a mod's extra files as separate mods (no merge or replace questions)
3. The mods then go to the bottom of MO2's left pane **in your list's order, under your list's separators**, and are switched on.

**Separators:** a line in your list starting with `##` becomes an MO2 separator, and the mods below it go under it:

```text
## 01 — EXTERNAL TOOLS AND CLEAN BASE
https://www.nexusmods.com/skyrimspecialedition/mods/...
## 02 — ENGINE, SKSE LIBRARIES, BUG FIXES
https://www.nexusmods.com/skyrimspecialedition/mods/...
```

Missing separators are created. Stage 4 shows the same headings, and **Share…** keeps them.

**The first time:** MO2 needs the add-on. **Start downloads** offers to add it (or use **Add installer to MO2**), and MO2 has to be restarted once after that. Keep MO2 open while it downloads and installs.

**Good to know:**
- If some downloads haven't arrived after 10 minutes, the add-on asks whether to install the ones that have.
- You can switch automatic installing off in MO2: **Settings → Plugins → SkyrimDownloaded Installer → auto_install**.
- In MO2, **Tools** (the puzzle-piece button) → **SkyrimDownloaded: install downloaded mods** runs it by hand.
- To skip the name question for mods without an installer, set **Settings → Plugins → Simple Installer → silent** to true in MO2.
- Run **Sort with LOOT** afterwards to sort the plugins.

Command line: `python -m skyrimdl mo2-addon` adds the add-on.

## Starting from a Nexus Collection

**List ▾ → Start from a Nexus Collection…** asks for a collection's link (e.g. `https://www.nexusmods.com/games/skyrimspecialedition/collections/abc123`, optionally ending in `/revisions/12`) and turns it into a normal list:

- **Every file is pinned**, so you get exactly the files the collection uses.
- **Mods the collection marks optional** ask before downloading.
- **Things the collection needs from outside Nexus** are listed as notes.

Then change it however you like: add mods, remove some, pick different files, before pressing **Look up mods**. The installer (FOMOD) choices stored in a collection aren't used; your mod manager asks for those when installing.

Command line: `python -m skyrimdl collection <link> -o my-list.txt`

## Sharing your list

**List ▾ → Share…** saves your list with every choice locked in: the exact files you picked, mods you left out, and the Skyrim version it was made for. Send that file to a friend. When they open it and press **Look up mods**, they get exactly the same files with no questions asked, which makes it the closest thing to your own collection.

- **It's an ordinary mod list.** Each line pins the files with `| file=…`, so you can read and edit it too.
- **Different Skyrim versions:** if the person has a different version than yours, they're told. Any pinned file that doesn't fit their version is flagged for them to choose again.
- **Command line:** `python -m skyrimdl run my-mods.txt --dry-run --export shared.txt`

## Checking for updates

**Check for updates** asks Nexus again about every file you picked:

| What Nexus shows | What the tool does |
|---|---|
| The author uploaded a newer version | It offers to switch to the newer file. Nexus links each old file to its replacement, so this is exact. |
| The file moved to *Old versions* or was removed | It suggests the current file from the same section of the Files tab, if there is one. Otherwise it lists the file so you can check the mod's page. |

Tick the ones you want, then **Start downloads** to get them. The command line has `python -m skyrimdl updates my-mods.txt`, and `--apply` switches your saved choices.

## Sorting the load order (LOOT)

**Sort with LOOT** opens [LOOT](https://loot.github.io); in LOOT, press **Sort Plugins**, then **Apply**.

- **MO2:** LOOT runs *through* MO2, so it can see your mods. If LOOT is one of the instance's executables (MO2 usually adds it by itself), it's started by that name. Otherwise the tool finds `LOOT.exe` (installed, or in a Wabbajack list's tools folder) and runs it through MO2.
- **Vortex:** Vortex sorts plugins itself (Plugins tab, **Sort now**). The button still opens LOOT on its own if you have it.
- **Command line:** `python -m skyrimdl loot`

## Nexus requests

Nexus allows a personal API key about 2,500 requests a day; after that, only about 100 an hour. The window shows how many you have left next to your name.

- **Looking up a mod costs about 2 requests.** What Nexus says is saved on your PC, so looking the same mod up again within 7 days costs nothing, whether it's the same list, a different list, or after a restart.
- **Refresh from Nexus** (next to **Look up mods**) fetches fresh data when you want it.
- **Check for updates** always asks Nexus.
- **You're warned first** if something would need more requests than you have left.

The saved data is in `%LOCALAPPDATA%\SkyrimDownloaded\nexus-cache.json`.

## New versions

Once a day the app checks GitHub for a newer release. If there is one, an **⬆ Update to …** button appears in the bottom bar. Press it and the app updates itself:
1. It downloads the new `SkyrimDownloaded.exe` and checks it against the checksum GitHub publishes for the release.
2. It closes, swaps the new version in, and reopens. Your work in progress is saved and comes back.

If the folder the app is in can't be written to, the new version goes to `%LOCALAPPDATA%\SkyrimDownloaded\app` and starts from there. **Help ▾ → Check for a new version / update** checks right away. When running from source, the button opens the release page instead.

## If something goes wrong

**Help ▾ → Copy debug info** puts the app version, your setup and the end of the log on the clipboard, ready to paste into a problem report. Your API key is never included. **Open log folder** shows the log itself (`%LOCALAPPDATA%\SkyrimDownloaded\skyrimdl.log`).

## Picking up where you left off

Your work is saved as you go and when you close the app. Next time it opens, everything is back where you left it:
- the mod list, including edits you haven't saved to a file
- every looked-up mod, with its files and the options you picked
- mods still waiting for a choice or skipped for later
- the compatibility results
- the view settings and the window size

**Save progress** saves straight away if you want to be sure. **List ▾ → Start over** clears everything for a new list; a list you saved to a file stays on disk.

The saved work is in `%APPDATA%\SkyrimDownloaded\session.json`. It holds what Nexus said when you last looked the mods up, so press **Look up mods** to refresh it if a while has passed. Your choices are kept.

## ESL and packed versions are preferred

Some mods offer the same file in more than one form: a regular plugin and an **ESL** (light) one, or **loose** files and a **packed** (BSA/BA2) archive. When files are just variants of each other, only one is ticked:

- **ESL beats regular, and packed beats loose.** Better Container Controls for SkyUI gets `BCC-SkyUI-ESL-v31`, not both of its files.
- **How variants are spotted:** their names match once those words are taken out, or an optional file's description says it's an alternative to the main file ("don't use both").
- **It never doubles up:** this applies to the first pick, to `| all` and `| main`, and to auto-ticked patches.

## Patches for mods in your list are ticked by themselves

After **Look up mods**, any file on a mod's Files tab that's meant for another mod in your list gets ticked. For example, EasyNPC's files for Pandorable or Interesting NPCs are ticked when those mods are in your list too.
- These files are marked ★ in the list. If you untick one, it stays unticked, even after another lookup or a restart.
- Files for other Skyrim versions are never ticked.
- This covers patches that are separate files on Nexus. Options inside a mod's installer window (FOMOD) are chosen when it installs.
- Command line: on by default; `--no-auto-patches` turns it off.

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
- **Command line:** add `--compat` to print the report after the options. It offers to tick the suggested patches.

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
| `--compat` | Also checks how the mods in the list relate to each other |
| `--export FILE` | Also saves a shareable copy of the list with every choice locked in |
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

## Releases

Releases are published by the **Build** workflow. It builds `SkyrimDownloaded.exe` (code-signed, once [SIGNING.md](SIGNING.md) is set up) and attaches it to a new release. Start it either way:

- **On GitHub:** go to **Actions → Build → Run workflow**, pick `main`, tick **Publish a release** and press **Run workflow**. The release is tagged with the version in `skyrimdl/__init__.py`, so bump that first.
- **With git:** push a version tag that matches that version.

  ```bash
  git tag v1.6.0
  ```

  ```bash
  git push origin v1.6.0
  ```

## Code signing policy

Free code signing provided by [SignPath.io](https://about.signpath.io), certificate by [SignPath Foundation](https://signpath.org) (once the project is accepted; see [SIGNING.md](SIGNING.md)).

- **What is signed:** only `SkyrimDownloaded.exe`, built from this repository's source by the GitHub Actions **Build** workflow on GitHub's own Windows machines. Nothing built anywhere else is signed.
- **Committers and reviewers:** [lordfulger](https://github.com/lordfulger), who writes and reviews the code in this repository.
- **Approvers:** [lordfulger](https://github.com/lordfulger) approves every signing request.
- **Privacy:** SkyrimDownloaded sends nothing anywhere except the services you use it with:
  - Nexus Mods, with your own API key
  - GitHub, once a day, to check for a new version
  - the download servers of the mods you choose

  It doesn't collect data about you, and your API key never leaves your PC except to go to Nexus Mods.

## License

MIT, see [LICENSE](LICENSE).

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
  sharing.py     export a list with every choice locked in
  updates.py     newer files for the ones you picked
  loot.py        open LOOT (through MO2 for MO2 setups)
  nexuscache.py  keep Nexus answers on disk to save API requests
  logs.py        the log file and "Copy debug info"
  appupdate.py   is there a newer release on GitHub?
  pictures.py    mod pictures for the info panel (Pillow; optional from source)
  collections.py turn a Nexus Collection into a list
  mo2addon.py    the MO2 add-on (installs downloads in list order) and its install plan
  gui/           the window, split by area (app.py ties it together)
  cli.py, gui.py command line and Tk window
```
