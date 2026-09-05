import type { ReactNode } from 'react';
import { Label } from '../ui';
export function Field({ id, label, help, error, children }: { id:string; label:string; help?:string; error?:string; children:ReactNode }) { return <div className="field"><Label htmlFor={id}>{label}</Label>{children}{help && <span id={id + '-help'} className="caption">{help}</span>}{error && <p id={id + '-error'} className="field-error">{error}</p>}</div>; }
export function fieldDescription(id:string, help?:string, error?:string) { return [help ? id + '-help' : '', error ? id + '-error' : ''].filter(Boolean).join(' ') || undefined; }
