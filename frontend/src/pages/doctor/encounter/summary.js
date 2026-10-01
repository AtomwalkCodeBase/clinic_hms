import { encounterApi } from "../../../api";
import { openDataUrlInNewTab } from "../../../utils/fileViewer";

// Real, printable consultation-summary PDF — server-rendered (reportlab,
// see apps/opd/pdf.py's generate_encounter_summary_pdf) rather than a
// plain-text file built client-side, so what the doctor hands the patient
// looks like an actual medical document, not a stray .txt. Same
// open-in-new-tab pattern as the front-desk invoice PDF and the patient
// portal's prescription/invoice receipts (see utils/fileViewer.js).
export async function downloadVisitSummary(encId) {
  const win = window.open("", "_blank");
  try {
    const res = await encounterApi.summaryPdf(encId);
    const data = res.data?.data || res.data;
    if (data?.file_data) {
      openDataUrlInNewTab(win, data.file_data);
    } else if (win) {
      win.close();
    }
  } catch (err) {
    if (win) win.close();
    window.alert(err?.data?.error || err?.message || "Could not generate the consultation summary PDF.");
  }
}
