import type { Meta, StoryObj } from "@storybook/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { ConnectPage } from "@/pages/onboarding/ConnectPage";
import { PermissionsPage } from "@/pages/onboarding/PermissionsPage";
import { WelcomePage } from "@/pages/onboarding/WelcomePage";

/**
 * Screens 01 and 02 as specified, plus the scope explanation page they both
 * link to. Switch the theme in the toolbar: these are the first screens
 * anyone sees, so they are the first that have to be right in both.
 */
const meta: Meta = {
  title: "Onboarding/Screens",
  parameters: { layout: "fullscreen" },
};
export default meta;

function at(path: string, element: React.ReactNode) {
  return (
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path={path.split("?")[0]} element={element} />
      </Routes>
    </MemoryRouter>
  );
}

export const Screen01Welcome: StoryObj = {
  name: "01 - Welcome",
  render: () => at("/", <WelcomePage />),
};

export const Screen02Connect: StoryObj = {
  name: "02 - Account connection",
  render: () => at("/onboarding/connect", <ConnectPage />),
};

export const Screen02Declined: StoryObj = {
  name: "02 - Consent declined",
  render: () => at("/onboarding/connect?error=access_denied", <ConnectPage />),
};

export const Permissions: StoryObj = {
  name: "Permissions and privacy",
  render: () => at("/permissions", <PermissionsPage />),
};
