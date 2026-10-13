// Hospital admin: the vaccination roadmap this hospital's staff and patient portal build against. The page itself is shared: components/schedules/HospitalSchedulePage.jsx.
import HospitalSchedulePage from "../../components/schedules/HospitalSchedulePage";
import { VACCINATION } from "../../components/schedules/scheduleKinds";

export default function VaccinationSchedulePage() {
  return <HospitalSchedulePage kind={VACCINATION} />;
}
