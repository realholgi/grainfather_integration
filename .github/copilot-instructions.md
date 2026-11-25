<!-- Use this file to provide workspace-specific custom instructions to Copilot. For more details, visit https://code.visualstudio.com/docs/copilot/copilot-customization#_use-a-githubcopilotinstructionsmd-file -->
## Project setup

The project started as a Python Home Assistant integration for the Grainfather web API.
The initial setup added the API client, coordinator, config flow, and sensors.
The integration and tests passed bytecode compilation.

The setup did not require VS Code extensions or a dedicated task. It did not
launch or debug Home Assistant. See the README for setup and next steps.

- Follow the Home Assistant custom component structure in `custom_components/grainfather`.
- Keep the Grainfather API client separate from Home Assistant entity code.
- Write only the code the integration needs, and make it easy to test. Confirm the live API contract before extending it.