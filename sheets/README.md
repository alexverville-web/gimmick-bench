# Studio results sheet (one-time setup, about 5 minutes)

Every benchmark run is sent to one Google Sheet. The full raw result is kept as
a JSON file in a Drive folder, and the Sheet gets readable rows:

- **Runs** tab: one row per run (computer, hardware, app versions, how many tests passed, link to the raw file).
- **Tests** tab: one row per test (status, reason, median, spread, every measured run).

Nothing is computed in the Sheet. Scores are calculated later from the raw files,
so the formulas can change without re-running anything.

## Steps

1. Create a new Google Sheet, for example "Gimmick Bench results".
2. In the Sheet: **Extensions > Apps Script**. Delete the sample code and paste the
   contents of [`Code.gs`](Code.gs). Save.
3. In the Apps Script editor, choose the `setup` function and click **Run**. Approve
   the permissions it asks for (it creates the two tabs and a Drive folder).
4. Open **Executions** (or the log) and copy the token it printed.
5. Click **Deploy > New deployment**, type **Web app**:
   - Execute as: **Me**
   - Who has access: **Anyone** (the token is what protects it)
   Copy the web app URL.
6. On each computer, put the URL and token in `~/GimmickBench/config.json`
   (Windows: `C:\Users\<you>\GimmickBench\config.json`), or run:

   ```
   python3 -m gimmick_bench configure --sheet-url "<web app URL>" --sheet-token "<token>"
   ```

The token is a shared secret. Keep it inside the studio; anyone with the URL and
token can add rows.

If the upload fails (offline, wrong token), the result is still saved locally in
`~/GimmickBench/results/` and can be sent later with `python3 -m gimmick_bench upload <file>`.
