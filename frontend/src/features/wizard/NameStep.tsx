import { useState, type FormEvent } from 'react'
import { ArrowRight } from 'lucide-react'
import { errorMessage, useCreateProject, useUpdateProject } from '@/api/hooks'
import type { Project } from '@/api/types'
import { Button, Card, Field, Input, Textarea } from '@/components/ui'
import { StepIntro, WizardBody, WizardFooter } from './WizardShell'

const MAX_NAME = 80

/** Step 1 — name + description. Creates the project (v1 = recommended config) or updates it when coming back. */
export function NameStep({ project, onNext }: { project?: Project; onNext: (p: Project) => void }) {
  const create = useCreateProject()
  const update = useUpdateProject(project?.id ?? '')
  const [name, setName] = useState(project?.name ?? '')
  const [description, setDescription] = useState(project?.description ?? '')
  const [touched, setTouched] = useState(false)
  const nameError = !name.trim() ? 'Give the project a name' : name.trim().length > MAX_NAME ? `Keep it under ${MAX_NAME} characters` : null
  const mutation = project ? update : create
  const pending = mutation.isPending

  const submit = (e: FormEvent) => {
    e.preventDefault()
    setTouched(true)
    if (nameError) return
    const body = { name: name.trim(), description: description.trim() }
    if (project) {
      if (body.name === project.name && body.description === project.description) return onNext(project)
      update.mutate(body, { onSuccess: onNext })
    } else {
      create.mutate(body, { onSuccess: onNext })
    }
  }

  return (
    <form onSubmit={submit} noValidate className="flex flex-1 flex-col">
      <WizardBody>
        <StepIntro
          title="Name your project"
          description="A project holds one document set and every version of its retrieval pipeline."
        />
        <Card padding="lg" className="flex flex-col gap-5">
          <Field label="Name" error={touched ? nameError : null} help="Shown on the projects page and in the API.">
            {(f) => (
              <Input
                id={f.id}
                aria-describedby={f.describedBy}
                invalid={f.invalid}
                required
                autoFocus
                maxLength={MAX_NAME + 20}
                placeholder="e.g. Pydantic docs"
                value={name}
                onChange={(e) => setName(e.target.value)}
                onBlur={() => setTouched(true)}
              />
            )}
          </Field>
          <Field label="Description" help="Optional — what’s in it and who it’s for.">
            {(f) => (
              <Textarea
                id={f.id}
                aria-describedby={f.describedBy}
                rows={3}
                placeholder="Pydantic v2 documentation — models, fields, validators and the error reference."
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            )}
          </Field>
          {mutation.isError && (
            <p role="alert" className="rounded-md border border-danger-border bg-danger-bg px-3 py-2 text-body text-danger-fg">
              {errorMessage(mutation.error)}
            </p>
          )}
        </Card>
      </WizardBody>
      <WizardFooter step={0} hint={project ? 'Step 1 of 4 · project created' : 'Step 1 of 4 · starts with the recommended pipeline'}>
        <Button type="submit" variant="primary" loading={pending} iconRight={<ArrowRight size={14} aria-hidden />}>
          {project ? 'Continue' : 'Create project'}
        </Button>
      </WizardFooter>
    </form>
  )
}
