import { http, API_ENDPOINTS } from "./http";

const { OPD, PATIENTS, LAB, IPD } = API_ENDPOINTS;

/** Everything the doctor's consultation workspace (pages/doctor/EncounterPage) sends to the backend. */
export const encounterApi = {
  // encounter
  save:            (id, payload)   => http.patch(OPD.ENCOUNTER(id), payload),
  sign:            (id)            => http.post(OPD.ENCOUNTER_SIGN(id), {}),
  summaryPdf:      (id)            => http.get(OPD.ENCOUNTER_PDF(id)),
  bookFollowUp:    (id, body)      => http.post(OPD.ENCOUNTER_FOLLOWUP(id), body),

  // handwriting (consult-pad) session
  createConsultSession:  (encId)       => http.post(OPD.ENCOUNTER_CONSULT_SESSION(encId)),
  getConsultSession:     (encId)       => http.get(OPD.ENCOUNTER_CONSULT_SESSION(encId)),
  recogniseConsultSession: (encId)     => http.post(OPD.ENCOUNTER_CONSULT_SESSION(encId), { action: "recognise" }),

  // prescription
  createPrescription:  (encounterId)   => http.post(OPD.PRESCRIPTIONS, { encounter_id: encounterId }),
  addPrescriptionItem: (rxId, item)    => http.post(OPD.PRESCRIPTION_ITEMS(rxId), item),
  removePrescriptionItem: (rxId, itemId) => http.delete(OPD.PRESCRIPTION_ITEM(rxId, itemId)),

  // favourite prescription bundles
  createFavourite: (name, items)       => http.post(OPD.FAVOURITES, { name, items }),
  deleteFavourite: (id)                => http.delete(OPD.FAVOURITE_ITEM(id)),

  // dictation
  transcribe: (formData) => http.post(OPD.TRANSCRIBE, formData, { headers: { "Content-Type": "multipart/form-data" } }),

  // investigations / referral
  orderLabTests:      (encounterId, testIds) => http.post(LAB.REQUESTS, { encounter_id: encounterId, tests: testIds }),
  recommendAdmission: (body)                 => http.post(IPD.REFERRAL_RECOMMEND, body),

  // pediatric / vaccination panels of the history sidebar
  orderVaccination:     (patientPk, body)  => http.post(PATIENTS.VACCINATION_ORDER(patientPk), body),
  declineVaccination:   (patientPk, body)  => http.post(PATIENTS.VACCINATION_DECLINE(patientPk), body),
  administerVaccination:(patientPk, body)  => http.post(PATIENTS.VACCINATION_ADMINISTER(patientPk), body),
  recordVaccination:    (patientPk, body)  => http.post(PATIENTS.VACCINATIONS(patientPk), body),
  verifyVaccination:    (recordId, action) => http.patch(PATIENTS.VACCINATION_VERIFY(recordId), { action }),
  saveBirthHistory:     (patientPk, body, exists) =>
    (exists ? http.patch : http.post)(PATIENTS.BIRTH_HISTORY(patientPk), body),
  addMilestone:         (patientPk, body)  => http.post(PATIENTS.MILESTONES(patientPk), body),
};
