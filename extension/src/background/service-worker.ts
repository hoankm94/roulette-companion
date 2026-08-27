import { CompanionController } from "./companion-controller.js";
import { MSG, type CompanionMessage } from "../shared/messages.js";

const controller = new CompanionController();
controller.init();

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  const typed = message as CompanionMessage;
  controller.noteContentTab(sender.tab?.id);
  const result = controller.handleMessage(typed);
  if (result instanceof Promise) {
    result.then(sendResponse);
    return true;
  }
  sendResponse(result);
  return true;
});
