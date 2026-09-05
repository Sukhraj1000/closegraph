import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { Button, Checkbox, Dialog, DialogContent, DialogTrigger, Label, Tabs, TabsContent, TabsList, TabsTrigger } from './ui';
describe('accessible shared primitives', () => {
  it('traps dialog focus, closes with Escape and returns focus to its trigger', async () => {
    const user = userEvent.setup();
    render(<Dialog><DialogTrigger asChild><Button>Open evidence</Button></DialogTrigger><DialogContent title="Source evidence" description="Original values are retained."><Button>Inspect original</Button></DialogContent></Dialog>);
    await user.click(screen.getByRole('button', { name: 'Open evidence' }));
    expect(screen.getByRole('dialog', { name: 'Source evidence' })).toBeVisible();
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Open evidence' })).toHaveFocus();
  });
  it('allows keyboard tab navigation and labelled checked controls', async () => {
    const user = userEvent.setup();
    render(<><Tabs defaultValue="source"><TabsList aria-label="Evidence"><TabsTrigger value="source">Source</TabsTrigger><TabsTrigger value="checks">Checks</TabsTrigger></TabsList><TabsContent value="source">Original document</TabsContent><TabsContent value="checks">Checks passed</TabsContent></Tabs><Checkbox id="attest" /><Label htmlFor="attest">I inspected the snapshot</Label><Button disabled>Publish</Button></>);
    screen.getByRole('tab', { name: 'Source' }).focus(); await user.keyboard('{ArrowRight}');
    expect(screen.getByRole('tab', { name: 'Checks' })).toHaveAttribute('aria-selected', 'true');
    await user.click(screen.getByText('I inspected the snapshot'));
    expect(screen.getByRole('checkbox')).toBeChecked();
    expect(screen.getByRole('button', { name: 'Publish' })).toBeDisabled();
  });
});
