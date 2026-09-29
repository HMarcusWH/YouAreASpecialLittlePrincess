import { DossierCopy, DossierScreen } from "../src/ui/DossierScreen.tsx";

export default function Reports() {
  return (
    <DossierScreen eyebrow="Server-authorized projections" title="Reports">
      <DossierCopy>
        T30/T31 will integrate account-backed report retrieval through the generated API client. No native
        measurement or report reconstruction is permitted here.
      </DossierCopy>
    </DossierScreen>
  );
}
