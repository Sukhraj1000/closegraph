import * as React from 'react';
import { Slot } from '@radix-ui/react-slot';
import * as DialogPrimitive from '@radix-ui/react-dialog';
import * as CheckboxPrimitive from '@radix-ui/react-checkbox';
import * as TabsPrimitive from '@radix-ui/react-tabs';
import * as AccordionPrimitive from '@radix-ui/react-accordion';
import * as TooltipPrimitive from '@radix-ui/react-tooltip';
import * as LabelPrimitive from '@radix-ui/react-label';
import { cva, type VariantProps } from 'class-variance-authority';
import { Check, ChevronDown, X } from 'lucide-react';
import { cn } from '../../lib/utils';

const buttonVariants = cva('button', { variants: { variant: { primary: 'button-primary', outline: 'button-outline', link: 'button-link' }, size: { default: '', sm: 'button-small', icon: 'button-icon' } }, defaultVariants: { variant: 'primary', size: 'default' } });
export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> { asChild?: boolean }
export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(({ className, variant, size, asChild = false, ...props }, ref) => { const Component = asChild ? Slot : 'button'; return <Component ref={ref} className={cn(buttonVariants({ variant, size }), className)} {...props} />; });
Button.displayName = 'Button';
export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(({ className, ...props }, ref) => <input ref={ref} className={cn('input', className)} {...props} />);
Input.displayName = 'Input';
export const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(({ className, ...props }, ref) => <textarea ref={ref} className={cn('input textarea', className)} {...props} />);
Textarea.displayName = 'Textarea';
export const Label = React.forwardRef<React.ElementRef<typeof LabelPrimitive.Root>, React.ComponentPropsWithoutRef<typeof LabelPrimitive.Root>>(({ className, ...props }, ref) => <LabelPrimitive.Root ref={ref} className={cn('label', className)} {...props} />);
Label.displayName = 'Label';
export function Card({ className, ...props }: React.HTMLAttributes<HTMLElement>) { return <section className={cn('card', className)} {...props} />; }
export type Tone = 'neutral' | 'success' | 'warning' | 'danger' | 'info';
export function Badge({ tone = 'neutral', className, ...props }: React.HTMLAttributes<HTMLSpanElement> & { tone?: Tone }) { return <span className={cn('badge', 'badge-' + tone, className)} {...props} />; }
export function Alert({ title, children, tone = 'info' }: { title: string; children?: React.ReactNode; tone?: Tone }) { return <div className={cn('alert', 'alert-' + tone)} ><strong>{title}</strong>{children && <div>{children}</div>}</div>; }
export const Checkbox = React.forwardRef<React.ElementRef<typeof CheckboxPrimitive.Root>, React.ComponentPropsWithoutRef<typeof CheckboxPrimitive.Root>>(({ className, ...props }, ref) => <CheckboxPrimitive.Root ref={ref} className={cn('checkbox', className)} {...props}><CheckboxPrimitive.Indicator><Check size={14} aria-hidden /></CheckboxPrimitive.Indicator></CheckboxPrimitive.Root>);
Checkbox.displayName = 'Checkbox';
export const Dialog = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;
export const DialogClose = DialogPrimitive.Close;
export function DialogContent({ title, description, children }: { title: string; description: string; children: React.ReactNode }) { return <DialogPrimitive.Portal><DialogPrimitive.Overlay className="dialog-overlay" /><DialogPrimitive.Content className="dialog-content"><DialogPrimitive.Title className="dialog-title">{title}</DialogPrimitive.Title><DialogPrimitive.Description className="muted">{description}</DialogPrimitive.Description>{children}<DialogPrimitive.Close className="dialog-close button button-outline button-icon" aria-label="Close dialog"><X size={18} /></DialogPrimitive.Close></DialogPrimitive.Content></DialogPrimitive.Portal>; }
export const Tabs = TabsPrimitive.Root;
export const TabsContent = TabsPrimitive.Content;
export const TabsList = React.forwardRef<React.ElementRef<typeof TabsPrimitive.List>, React.ComponentPropsWithoutRef<typeof TabsPrimitive.List>>(({ className, ...props }, ref) => <TabsPrimitive.List ref={ref} className={cn('tabs-list', className)} {...props} />);
TabsList.displayName = 'TabsList';
export const TabsTrigger = React.forwardRef<React.ElementRef<typeof TabsPrimitive.Trigger>, React.ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>>(({ className, ...props }, ref) => <TabsPrimitive.Trigger ref={ref} className={cn('tabs-trigger', className)} {...props} />);
TabsTrigger.displayName = 'TabsTrigger';
export const Accordion = AccordionPrimitive.Root;
export const AccordionItem = AccordionPrimitive.Item;
export function AccordionTrigger({ children, ...props }: React.ComponentPropsWithoutRef<typeof AccordionPrimitive.Trigger>) { return <AccordionPrimitive.Header><AccordionPrimitive.Trigger className="accordion-trigger" {...props}>{children}<ChevronDown size={16} aria-hidden /></AccordionPrimitive.Trigger></AccordionPrimitive.Header>; }
export const AccordionContent = AccordionPrimitive.Content;
export function Tooltip({ children, label }: { children: React.ReactNode; label: string }) { return <TooltipPrimitive.Provider delayDuration={250}><TooltipPrimitive.Root><TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger><TooltipPrimitive.Portal><TooltipPrimitive.Content className="tooltip" sideOffset={6}>{label}<TooltipPrimitive.Arrow /></TooltipPrimitive.Content></TooltipPrimitive.Portal></TooltipPrimitive.Root></TooltipPrimitive.Provider>; }
