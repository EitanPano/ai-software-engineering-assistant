import { expect, type Locator, test } from '@playwright/test'

import { settled } from './support'

// `settled` backs every axe scan, so it must survive what a live page does: a transition that is
// retargeted or removed mid-fade cancels its animation, and the replacement must still be awaited.
const PAGE = `
  <style>
    #host button { opacity: 1; transition: opacity 400ms linear; }
    #host button:disabled { opacity: 0.5; }
  </style>
  <div id="host"><button disabled>Send</button></div>
`

// Starts the fade and holds it mid-way: at a rate of 0 it stays running until the test cancels it,
// so `settled` meets it however loaded the machine is. Wall-clock timers could not promise that:
// one landing after `settled` saw nothing running restarted a fade it would never wait for.
async function holdFade(host: Locator) {
  await host.locator('button').evaluate((button: HTMLButtonElement) => {
    button.getBoundingClientRect() // the computed style a transition starts from
    button.disabled = false // fades up
    const [fade] = button.getAnimations()
    if (!fade) throw new Error('no fade')
    fade.currentTime = 200
    fade.playbackRate = 0
  })
}

test.describe('settled', () => {
  test('waits for a replacement transition when the first is cancelled mid-fade', async ({
    page,
  }) => {
    await page.setContent(PAGE)
    const host = page.locator('#host')
    await holdFade(host)

    await Promise.all([
      settled(host),
      host.locator('button').evaluate((button: HTMLButtonElement) => {
        button.disabled = true // retarget: cancels the held fade, starts a fade down
      }),
    ])

    // Nothing finite is left running, and the button rests at its end state.
    const running = await host.evaluate(
      (element) =>
        element.getAnimations({ subtree: true }).filter((a) => a.playState === 'running').length,
    )
    expect(running).toBe(0)
    const opacity = await page
      .getByRole('button', { name: 'Send' })
      .evaluate((element) => getComputedStyle(element).opacity)
    expect(opacity).toBe('0.5')
  })

  test('resolves when a finished animation holds its end state with fill forwards', async ({
    page,
  }) => {
    await page.setContent(`<div id="host"><p id="note">Done</p></div>`)
    const host = page.locator('#host')
    await host.evaluate((element) => {
      const note = element.querySelector('#note')
      if (!note) throw new Error('no note')
      // 100 ms fade-in that stays in getAnimations() after it finishes.
      note.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 100, fill: 'forwards' })
    })

    await settled(host)

    const state = await host.evaluate((element) =>
      element.getAnimations({ subtree: true }).map((a) => a.playState),
    )
    expect(state).toEqual(['finished'])
    await expect(page.locator('#note')).toHaveCSS('opacity', '1')
  })

  test('resolves when the animated element is removed mid-fade', async ({ page }) => {
    await page.setContent(PAGE)
    const host = page.locator('#host')
    await holdFade(host)

    await Promise.all([
      expect(settled(host)).resolves.toBeUndefined(),
      host.locator('button').evaluate((button) => {
        button.remove()
      }),
    ])
  })
})
