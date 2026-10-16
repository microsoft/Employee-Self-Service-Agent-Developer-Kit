async (page, options = {}) => {
  const capture = options.capture !== false;
  const destinationUrl =
    "https://entra.microsoft.com/#view/Microsoft_AAD_IAM/ActiveDirectoryMenuBlade/~/Overview";
  if (page.url() !== destinationUrl) {
    try {
      await page.goto(destinationUrl);
      await page.waitForURL(destinationUrl, { timeout: 10000 });
    } catch {
      return {
        ok: false,
        failedAt: "navigate-directory-overview",
        url: page.url(),
        error: "Initial direct navigation attempt failed",
      };
    }
  }

  let directory = null;
  for (let attempt = 0; attempt < 20 && !directory; attempt += 1) {
    for (const frame of page.frames()) {
      const matches = frame.getByText("EmployeeHub", { exact: true });
      for (let index = 0; index < (await matches.count()); index += 1) {
        const candidate = matches.nth(index);
        if (await candidate.isVisible().catch(() => false)) {
          directory = candidate;
          break;
        }
      }
      if (directory) {
        break;
      }
    }
    if (!directory) {
      await page.waitForTimeout(500);
    }
  }
  if (!directory) {
    return {
      ok: false,
      failedAt: "locate-directory-name",
      url: page.url(),
    };
  }

  const value = capture ? (await directory.innerText()).trim() : null;
  if (capture && !value) {
    return {
      ok: false,
      failedAt: "read-directory-name",
      url: page.url(),
    };
  }
  const box = await directory.boundingBox();
  if (!box) {
    return {
      ok: false,
      failedAt: "measure-directory-name",
      url: page.url(),
    };
  }
  const viewport = await page.evaluate(() => ({
    width: innerWidth,
    height: innerHeight,
  }));
  const center = box.y + box.height / 2;
  const result = {
    ok: true,
    targets: [
      {
        label: capture ? value : "Directory name",
        positionRatio:
          Math.round(
            Math.min(Math.max(center / viewport.height, 0.05), 0.95) * 10000,
          ) / 10000,
        centered:
          Math.abs(center - viewport.height / 2) <=
          Math.max(24, box.height / 2),
      },
    ],
  };
  if (capture) {
    result.value = value;
  }
  return result;
};
