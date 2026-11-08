import type { Meta, StoryObj } from "@storybook/react";
import { ArrowRight, Check, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";

const meta: Meta<typeof Button> = {
  title: "Design system/Button",
  component: Button,
  parameters: { layout: "padded" },
  args: { children: "Get started" },
};
export default meta;

type Story = StoryObj<typeof Button>;

export const Variants: Story = {
  render: () => (
    <div className="flex flex-wrap items-center gap-s1">
      <Button>Primary</Button>
      <Button variant="secondary">Secondary</Button>
      <Button variant="ghost">Ghost</Button>
      <Button variant="subtle">Subtle</Button>
      <Button variant="ai">
        <Sparkles aria-hidden />
        AI action
      </Button>
      <Button variant="danger">Disconnect</Button>
      <Button variant="link">Permissions and privacy</Button>
    </div>
  ),
};

export const Sizes: Story = {
  render: () => (
    <div className="flex flex-wrap items-center gap-s1">
      <Button size="sm">Small</Button>
      <Button size="md">Medium</Button>
      <Button size="lg">
        Get started
        <ArrowRight aria-hidden />
      </Button>
      <Button size="icon" aria-label="Confirm">
        <Check aria-hidden />
      </Button>
      <Button size="icon-sm" aria-label="Confirm">
        <Check aria-hidden />
      </Button>
    </div>
  ),
};

export const Disabled: Story = {
  args: { disabled: true },
};
