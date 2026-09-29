import { DossierCopy, DossierScreen } from "../src/ui/DossierScreen.tsx";

export default function History() {
  return (
    <DossierScreen eyebrow="Account-backed" title="History">
      <DossierCopy>
        History is a native presentation of saved report revisions. System report dates are not relabelled as
        handwriting dates.
      </DossierCopy>
    </DossierScreen>
  );
}
