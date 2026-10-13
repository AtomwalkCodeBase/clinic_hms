// Platform admin: the system milestone schedule templates hospital admins clone from. The page itself is shared: components/schedules/PlatformTemplatesPage.jsx.
import PlatformTemplatesPage from "../../components/schedules/PlatformTemplatesPage";
import { MILESTONE } from "../../components/schedules/scheduleKinds";

export default function MilestoneTemplatesPage() {
  return <PlatformTemplatesPage kind={MILESTONE} />;
}
