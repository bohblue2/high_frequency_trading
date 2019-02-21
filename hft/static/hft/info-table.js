import { PolymerElement, html } from './node_modules/@polymer/polymer/polymer-element.js';

class InfoTable extends PolymerElement {
    static get properties() {
      return {
        bestBid: Number,
        bestOffer: Number,
        myBid: Number,
        myOffer: Number,        
        inventory: Number, 
        cash: Number,
        endowment: Number,
        orderImbalance: Number
      }
    }
    constructor() {
      super();
    }

    static get template() { 
        return html`
  
        <style>
        :host {
          display: inline-block;
          height: 100%;
          width: 100%;
          font-family: monospace;
        }
  
        .container {
          display: flex;
          flex-direction: row;
          justify-content: flex-start;
          align-items: center;
          height: 100%;
          width: 100%;
          background: #4F759B;
        }

        .title {
          display: inline-block;
          width: 33%;
          text-align: center;
          background: #FFFFF0;
        }
  
        .row {
          display: inline-block;
          margin: 5px;
          width: 33%;
          height: 100%;
        }

        #small-row {
          margin: 5px;
          width: 34%;
          height: 100%;
          align-items: flex-start;
        }
  
        </style>
          <div class="container">
            <div class="row">
              <bidask-spread title-left="Best Bid" title-right="Best Ask"
                bid={{bestBid}} ask={{bestOffer}}>
              </bidask-spread>
            </div>
            <div class="row">
              <bidask-spread title-left="My Bid" title-right="My Ask"
                bid={{myBid}} ask={{myOffer}}>
              </bidask-spread>
            </div>
            <div id="small-row" class="row">
              <subject-wallet inventory={{inventory}} cash={{cash}}
                endowment={{endowment}} order-imbalance={{orderImbalance}}> 
              </subject-wallet>
            </div>
          </div>
        `;}
  
  }
  customElements.define('info-table', InfoTable)