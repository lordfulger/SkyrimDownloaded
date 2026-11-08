# Code signing

Without a signature, Windows SmartScreen says *"Windows protected your PC … Unknown publisher"*, and browsers and antivirus programs are quicker to block the download. A signed `SkyrimDownloaded.exe` shows a publisher instead.

The **Build** workflow can sign the `.exe` either way below. Each route is switched off until its settings exist in GitHub. Set up **one** of them; if both are set up, SignPath is used.

| | **A. SignPath Foundation** (recommended) | **B. Azure Trusted Signing** |
|---|---|---|
| Cost | Free for open-source projects | About US$10 a month |
| Who can get it | Open-source projects SignPath accepts (this repo's MIT license qualifies) | Individuals in the USA or Canada, or registered organisations; Microsoft checks your identity |
| Publisher shown | "SignPath Foundation" | Your own name |
| Time | Application review, usually days to a few weeks | Identity check, usually a few days |

Either way, SmartScreen builds trust over time, so a brand-new signature can still show a warning for a while until enough people have run the signed app.

---

## A. SignPath Foundation (free)

### 1. Apply
Apply at <https://signpath.org/apply>. The README already has the **code signing policy** section SignPath asks for (roles, what is signed, privacy). Text you can use in the application:

> **Project:** SkyrimDownloaded — https://github.com/lordfulger/SkyrimDownloaded
> **License:** MIT
> **Description:** A free Windows tool for Skyrim Special/Anniversary Edition players. It takes a list of Nexus Mods links, lets the user choose each mod's files, and downloads them into Mod Organizer 2 or Vortex using the user's own Nexus account (official Nexus API), much like a Vortex Collection built from your own list.
> **Build:** Built only by GitHub Actions on GitHub-hosted Windows runners (`.github/workflows/build.yml`), with PyInstaller from the repository's Python source. Releases are published from that workflow.
> **What to sign:** `SkyrimDownloaded.exe`, a single file.
> **Roles:** lordfulger, author, reviewer and approver.

SignPath's rules include using two-factor authentication on your GitHub account (Settings → Password and authentication).

### 2. Once you're accepted
In the SignPath web app:
1. Note the **Organization ID**, the **project slug** (e.g. `SkyrimDownloaded`) and the **signing policy slug** (usually `release-signing`).
2. Make sure the project's trusted build system is **GitHub.com**, linked to this repository, and its artifact configuration signs a single `SkyrimDownloaded.exe`. SignPath's onboarding walks through this.
3. Create an **API token** for a user that can submit signing requests.

### 3. Tell GitHub
In this repository, go to **Settings → Secrets and variables → Actions**:

| Add as… | Name | Value |
|---|---|---|
| Secret | `SIGNPATH_API_TOKEN` | the API token |
| Variable | `SIGNPATH_ORGANIZATION_ID` | the organization ID |
| Variable | `SIGNPATH_PROJECT_SLUG` | the project slug |
| Variable | `SIGNPATH_SIGNING_POLICY_SLUG` | the signing policy slug |

---

## B. Azure Trusted Signing (paid, your own name)

1. **Create the signing account.** You need an Azure account (<https://portal.azure.com>). Create a **Trusted Signing Account**, pick the region closest to you, and note its **endpoint**, e.g. `https://eus.codesigning.azure.net/`.
2. **Get your identity checked.** In that account, create an **identity validation** (Public, Individual or Organization) and complete Microsoft's check.
3. **Create a certificate profile.** Once you're validated, create a **certificate profile** of type *Public Trust*.
4. **Create the login GitHub will use.** In **Microsoft Entra ID → App registrations**, register an app, e.g. "SkyrimDownloaded signing", and create a **client secret** for it. Note the tenant ID, client ID and the secret.
5. **Give that login permission to sign.** In the Trusted Signing Account's **Access control (IAM)**, give that app the role **Trusted Signing Certificate Profile Signer**.
6. **Tell GitHub.** In this repository, go to **Settings → Secrets and variables → Actions**:

| Add as… | Name | Value |
|---|---|---|
| Secret | `AZURE_TENANT_ID` | the tenant ID |
| Secret | `AZURE_CLIENT_ID` | the app's client ID |
| Secret | `AZURE_CLIENT_SECRET` | the client secret |
| Variable | `AZURE_SIGNING_ENDPOINT` | the endpoint, e.g. `https://eus.codesigning.azure.net/` |
| Variable | `AZURE_SIGNING_ACCOUNT` | the Trusted Signing Account's name |
| Variable | `AZURE_CERTIFICATE_PROFILE` | the certificate profile's name |

---

## After setting it up
Publish the next release as usual: **Actions → Build → Run workflow**, tick **Publish a release**.

The build then signs the `.exe` and checks the signature, failing loudly if it isn't valid. Once the signature passes, the release notes stop mentioning the SmartScreen warning. To check a downloaded copy: right-click `SkyrimDownloaded.exe` → **Properties → Digital Signatures**.

Neither route could be tried while writing this (both need your account). If the first signed build fails, the **Sign with …** step's error usually names the setting to fix. Send it over and it can be sorted out.
