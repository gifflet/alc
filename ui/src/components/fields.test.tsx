import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Field } from './fields'

describe('Field hint', () => {
  it('describes the control without becoming its name', () => {
    render(
      <Field label="Engine" hint="Which coding agent does the work">
        <select aria-label="Engine" />
      </Field>,
    )
    // Inside the <label>, the hint joins the accessible name and a screen
    // reader announces "Engine Which coding agent does the work" as the field.
    expect(screen.getByLabelText('Engine')).toBeInTheDocument()
    expect(screen.getByText('Which coding agent does the work')).toBeInTheDocument()
  })
})
