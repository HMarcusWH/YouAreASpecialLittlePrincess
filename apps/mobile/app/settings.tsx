import { DossierCopy, DossierScreen } from "../src/ui/DossierScreen.tsx";

export default function Settings() {
  return (
    <DossierScreen eyebrow="Privacy and account" title="Settings">
      <DossierCopy>
        Session, notification, deletion and provider settings remain application-authorized. Account switching
        clears sensitive native state and invalidates late responses.
      </DossierCopy>
    </DossierScreen>
  );
}
