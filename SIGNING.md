# Code signing (optional)

Without a signature, Windows SmartScreen shows *"Windows protected your PC … Unknown publisher"* the first time someone runs `SkyrimDownloaded.exe`. Signing the `.exe` shows your name as the publisher instead.

The **Build** workflow can already sign the `.exe` with [SignPath](https://signpath.io). It's switched off until the settings below exist. [SignPath Foundation](https://signpath.org) signs open-source projects for free; this repo's MIT license qualifies, but it's up to SignPath to accept the project.

## 1. Apply to SignPath Foundation
1. Read the requirements and apply at <https://signpath.org/apply>, giving this repository's address.
2. Once you're accepted, SignPath sets up an organization and a project for you. In the SignPath web app, note:
   - the **Organization ID**
   - the **project slug**, for example `SkyrimDownloaded`
   - the **signing policy slug**, usually `release-signing`
3. In SignPath, connect the project to **GitHub Actions** as its trusted build system, as their onboarding explains. The project's artifact configuration should sign a single `.exe` (`SkyrimDownloaded.exe`).
4. Create an **API token** for a SignPath user that is allowed to submit signing requests.

## 2. Add the settings to GitHub
Go to the repository's **Settings → Secrets and variables → Actions**.

| Add as… | Name | Value |
|---|---|---|
| Secret | `SIGNPATH_API_TOKEN` | the API token |
| Variable | `SIGNPATH_ORGANIZATION_ID` | the organization ID |
| Variable | `SIGNPATH_PROJECT_SLUG` | the project slug |
| Variable | `SIGNPATH_SIGNING_POLICY_SLUG` | the signing policy slug |

From then on, every build sends the `.exe` to SignPath, waits for the signed copy, and publishes that. The release notes stop mentioning the SmartScreen warning.

## Notes
- **What the workflow does.** It uploads the unsigned `.exe` as an artifact, submits it with SignPath's `signpath/github-action-submit-signing-request@v1` action, and copies the signed file back.
- **Not tested yet.** These steps couldn't be tried without a SignPath account. If the first signed build fails, the error in the **Sign with SignPath** step usually names the setting to fix.
- **SmartScreen may still warn for a while.** It builds trust in a publisher over time, so a new signature can still show a warning until enough people have run the signed app.
