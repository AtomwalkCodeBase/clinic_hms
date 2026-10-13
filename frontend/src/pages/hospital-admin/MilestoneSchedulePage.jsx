// Hospital admin: the developmental-milestone roadmap this hospital's staff build against. The page itself is shared: components/schedules/HospitalSchedulePage.jsx.
import HospitalSchedulePage from "../../components/schedules/HospitalSchedulePage";
import { MILESTONE } from "../../components/schedules/scheduleKinds";

export default function MilestoneSchedulePage() {
  return <HospitalSchedulePage kind={MILESTONE} />;
}
