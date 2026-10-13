// Platform admin: the system vaccination schedule templates hospital admins clone from. The page itself is shared: components/schedules/PlatformTemplatesPage.jsx.
import PlatformTemplatesPage from "../../components/schedules/PlatformTemplatesPage";
import { VACCINATION } from "../../components/schedules/scheduleKinds";

export default function VaccinationTemplatesPage() {
  return <PlatformTemplatesPage kind={VACCINATION} />;
}
